//! Undo/redo history.
//!
//! Generic over the entry payload so the GPU side can attach its own data
//! (e.g. texture tile snapshots) while the stack logic stays testable. The
//! stack never applies anything itself: `undo()` hands back the entry and the
//! caller reverts it. Entries pushed out of the history are returned so the
//! caller can free whatever they hold.

pub struct Entry<T> {
    pub label: String,
    pub data: T,
}

pub struct UndoStack<T> {
    undo: Vec<Entry<T>>,
    redo: Vec<Entry<T>>,
    pub max_entries: usize,
}

impl<T> Default for UndoStack<T> {
    fn default() -> Self {
        Self { undo: Vec::new(), redo: Vec::new(), max_entries: 200 }
    }
}

impl<T> UndoStack<T> {
    /// Record a new action. Clears the redo branch. Returns dropped entries.
    #[must_use]
    pub fn push(&mut self, label: impl Into<String>, data: T) -> Vec<Entry<T>> {
        let mut dropped: Vec<Entry<T>> = self.redo.drain(..).collect();
        self.undo.push(Entry { label: label.into(), data });
        if self.undo.len() > self.max_entries {
            let n = self.undo.len() - self.max_entries;
            dropped.extend(self.undo.drain(..n));
        }
        dropped
    }

    /// Move the newest action to the redo branch and return it for reverting.
    pub fn undo(&mut self) -> Option<&mut Entry<T>> {
        let e = self.undo.pop()?;
        self.redo.push(e);
        self.redo.last_mut()
    }

    /// Move the newest undone action back and return it for re-applying.
    pub fn redo(&mut self) -> Option<&mut Entry<T>> {
        let e = self.redo.pop()?;
        self.undo.push(e);
        self.undo.last_mut()
    }

    pub fn can_undo(&self) -> bool {
        !self.undo.is_empty()
    }
    pub fn can_redo(&self) -> bool {
        !self.redo.is_empty()
    }
    pub fn undo_label(&self) -> Option<&str> {
        self.undo.last().map(|e| e.label.as_str())
    }
    pub fn redo_label(&self) -> Option<&str> {
        self.redo.last().map(|e| e.label.as_str())
    }
    /// Labels oldest first, plus how many of them are currently applied.
    pub fn history(&self) -> (Vec<&str>, usize) {
        let mut v: Vec<&str> = self.undo.iter().map(|e| e.label.as_str()).collect();
        let applied = v.len();
        v.extend(self.redo.iter().rev().map(|e| e.label.as_str()));
        (v, applied)
    }

    /// All entries, applied and undone.
    pub fn entries(&self) -> impl Iterator<Item = &Entry<T>> {
        self.undo.iter().chain(self.redo.iter())
    }

    /// Drop the oldest entries until `cost` summed over all entries fits `budget`.
    #[must_use]
    pub fn trim_to_budget(&mut self, budget: u64, cost: impl Fn(&T) -> u64) -> Vec<Entry<T>> {
        let mut total: u64 = self.entries().map(|e| cost(&e.data)).sum();
        let mut dropped = Vec::new();
        // The far end of the redo branch is the least likely to be wanted.
        while total > budget && !self.redo.is_empty() {
            let e = self.redo.remove(0);
            total -= cost(&e.data);
            dropped.push(e);
        }
        while total > budget && !self.undo.is_empty() {
            let e = self.undo.remove(0);
            total -= cost(&e.data);
            dropped.push(e);
        }
        dropped
    }

    pub fn clear(&mut self) -> Vec<Entry<T>> {
        let mut v: Vec<Entry<T>> = self.undo.drain(..).collect();
        v.extend(self.redo.drain(..));
        v
    }

    pub fn len(&self) -> usize {
        self.undo.len() + self.redo.len()
    }
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A toy document: a number changed by recorded deltas.
    fn apply_undo(s: &mut UndoStack<i32>, value: &mut i32) -> bool {
        match s.undo() {
            Some(e) => {
                *value -= e.data;
                true
            }
            None => false,
        }
    }
    fn apply_redo(s: &mut UndoStack<i32>, value: &mut i32) -> bool {
        match s.redo() {
            Some(e) => {
                *value += e.data;
                true
            }
            None => false,
        }
    }

    #[test]
    fn undo_redo_round_trip() {
        let mut s = UndoStack::default();
        let mut v = 0;
        for d in [1, 2, 3] {
            v += d;
            assert!(s.push(format!("+{d}"), d).is_empty());
        }
        assert_eq!(v, 6);
        assert!(apply_undo(&mut s, &mut v));
        assert!(apply_undo(&mut s, &mut v));
        assert_eq!(v, 1);
        assert_eq!(s.redo_label(), Some("+2"));
        assert!(apply_redo(&mut s, &mut v));
        assert_eq!(v, 3);
        assert_eq!(s.history(), (vec!["+1", "+2", "+3"], 2));
    }

    #[test]
    fn new_action_discards_redo_branch() {
        let mut s = UndoStack::default();
        let _ = s.push("a", 1);
        let _ = s.push("b", 2);
        s.undo();
        let dropped = s.push("c", 3);
        assert_eq!(dropped.len(), 1);
        assert_eq!(dropped[0].label, "b");
        assert!(!s.can_redo());
        assert_eq!(s.history().0, vec!["a", "c"]);
    }

    #[test]
    fn empty_stack_is_safe() {
        let mut s: UndoStack<i32> = UndoStack::default();
        assert!(s.undo().is_none());
        assert!(s.redo().is_none());
        assert!(!s.can_undo());
    }

    #[test]
    fn max_entries_drops_oldest() {
        let mut s = UndoStack { max_entries: 3, ..Default::default() };
        let mut dropped = Vec::new();
        for i in 0..5 {
            dropped.extend(s.push(i.to_string(), i));
        }
        assert_eq!(dropped.iter().map(|e| e.data).collect::<Vec<_>>(), vec![0, 1]);
        assert_eq!(s.len(), 3);
    }

    #[test]
    fn budget_trims_redo_first_then_oldest() {
        let mut s = UndoStack::default();
        for i in 1..=4 {
            let _ = s.push(i.to_string(), i * 10);
        }
        s.undo(); // 40 moves to redo
        let dropped = s.trim_to_budget(50, |&c| c as u64);
        // total 100: drop redo 40 -> 60, then oldest 10 -> 50
        assert_eq!(dropped.iter().map(|e| e.data).collect::<Vec<_>>(), vec![40, 10]);
        assert_eq!(s.history(), (vec!["2", "3"], 2));
    }
}
