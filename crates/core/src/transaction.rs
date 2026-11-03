//! Recoverable directory saves. Writers hold an OS lock, stage a complete copy,
//! then rename the previous generation to a backup before publishing the new one.
//! A process interrupted between renames is recovered on the next open/save.
use anyhow::{bail, Context, Result};
use std::fs::{self, File, OpenOptions};
use std::path::{Path, PathBuf};

pub struct Transaction {
    target: PathBuf,
    stage: PathBuf,
    backup: PathBuf,
    _lock: File,
}

fn sibling(path: &Path, suffix: &str) -> Result<PathBuf> {
    let mut name = path
        .file_name()
        .context("project needs a folder name")?
        .to_os_string();
    name.push(suffix);
    Ok(path.with_file_name(name))
}

fn locked(path: &Path) -> Result<Transaction> {
    let target = std::path::absolute(path)?;
    fs::create_dir_all(target.parent().context("project needs a parent folder")?)?;
    let lock = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(sibling(&target, ".save-lock")?)?;
    lock.try_lock()
        .map_err(|e| anyhow::anyhow!("project is busy: {e}"))?;
    Ok(Transaction {
        stage: sibling(&target, ".save-stage")?,
        backup: sibling(&target, ".save-backup")?,
        target,
        _lock: lock,
    })
}

fn copy_tree(from: &Path, to: &Path) -> Result<()> {
    fs::create_dir_all(to)?;
    for entry in fs::read_dir(from)? {
        let entry = entry?;
        let kind = entry.file_type()?;
        let dest = to.join(entry.file_name());
        if kind.is_symlink() {
            bail!(
                "project save does not follow symlinks: {}",
                entry.path().display()
            );
        } else if kind.is_dir() {
            copy_tree(&entry.path(), &dest)?;
        } else if kind.is_file() {
            fs::copy(entry.path(), dest)?;
        } else {
            bail!("unsupported project entry: {}", entry.path().display());
        }
    }
    Ok(())
}

fn sync_tree(path: &Path) -> Result<()> {
    for entry in fs::read_dir(path)? {
        let entry = entry?;
        if entry.file_type()?.is_dir() {
            sync_tree(&entry.path())?;
        } else {
            File::open(entry.path())?.sync_all()?;
        }
    }
    sync_dir(path)
}

fn sync_dir(path: &Path) -> Result<()> {
    #[cfg(unix)]
    File::open(path)?.sync_all()?;
    #[cfg(not(unix))]
    let _ = path;
    Ok(())
}

impl Transaction {
    fn restore(&self) -> Result<bool> {
        if self.backup.exists() && !self.target.exists() {
            fs::rename(&self.backup, &self.target)?;
            sync_dir(self.target.parent().unwrap())?;
            return Ok(true);
        }
        Ok(false)
    }

    pub fn begin(path: &Path) -> Result<Self> {
        let tx = locked(path)?;
        tx.restore()?;
        if fs::symlink_metadata(&tx.target).is_ok_and(|m| m.file_type().is_symlink()) {
            bail!("project folder cannot be a symlink");
        }
        if tx.backup.exists() {
            fs::remove_dir_all(&tx.backup)?;
        }
        if tx.stage.exists() {
            fs::remove_dir_all(&tx.stage)?;
        }
        if tx.target.exists() {
            copy_tree(&tx.target, &tx.stage)?;
        } else {
            fs::create_dir_all(&tx.stage)?;
        }
        Ok(tx)
    }

    pub fn path(&self) -> &Path {
        &self.stage
    }

    pub fn commit(self) -> Result<()> {
        sync_tree(&self.stage)?;
        if self.target.exists() {
            fs::rename(&self.target, &self.backup)?;
        }
        sync_dir(self.target.parent().unwrap())?;
        if let Err(e) = fs::rename(&self.stage, &self.target) {
            self.restore().context("restoring previous save")?;
            return Err(e.into());
        }
        sync_dir(self.target.parent().unwrap())?;
        // The new generation is committed. Cleanup failure must not report a
        // failed save; a later begin will remove the old generation.
        if self.backup.exists() {
            let _ = fs::remove_dir_all(&self.backup);
        }
        Ok(())
    }
}

/// Restore the previous complete generation if publication was interrupted.
pub fn recover(path: &Path) -> Result<bool> {
    // Ordinary reads, including read-only project folders, need no write access.
    if !sibling(path, ".save-backup")?.exists() {
        return Ok(false);
    }
    locked(path)?.restore()
}

#[cfg(test)]
mod tests {
    use super::*;
    fn root(name: &str) -> PathBuf {
        let p = std::env::temp_dir().join(format!("pigment-tx-{}-{name}", std::process::id()));
        let _ = fs::remove_dir_all(&p);
        fs::create_dir_all(&p).unwrap();
        p
    }
    #[test]
    fn aborted_save_preserves_all_files_and_commit_replaces_generation() {
        let root = root("commit");
        let path = root.join("project");
        fs::create_dir(&path).unwrap();
        fs::write(path.join("old"), "old").unwrap();
        {
            let tx = Transaction::begin(&path).unwrap();
            fs::write(tx.path().join("old"), "partial").unwrap();
            assert!(Transaction::begin(&path).is_err());
        }
        assert_eq!(fs::read_to_string(path.join("old")).unwrap(), "old");
        let tx = Transaction::begin(&path).unwrap();
        assert_eq!(fs::read_to_string(tx.path().join("old")).unwrap(), "old");
        fs::write(tx.path().join("old"), "new").unwrap();
        fs::create_dir_all(tx.path().join("sets/extra")).unwrap();
        fs::write(tx.path().join("sets/extra/data"), "set").unwrap();
        tx.commit().unwrap();
        assert_eq!(fs::read_to_string(path.join("old")).unwrap(), "new");
        assert!(path.join("sets/extra/data").exists());
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn interruption_between_renames_recovers_previous_generation() {
        let root = root("recover");
        let path = root.join("project");
        fs::create_dir(&path).unwrap();
        fs::write(path.join("data"), "old").unwrap();
        let tx = Transaction::begin(&path).unwrap();
        fs::write(tx.path().join("data"), "new").unwrap();
        fs::rename(&tx.target, &tx.backup).unwrap();
        drop(tx);
        assert!(recover(&path).unwrap());
        assert_eq!(fs::read_to_string(path.join("data")).unwrap(), "old");
        assert!(!recover(&path).unwrap());
        fs::remove_dir_all(root).unwrap();
    }
}
