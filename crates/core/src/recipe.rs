//! Versioned recipes use typed parameter references, not string substitution.
use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Call {
    pub tool: String,
    #[serde(default = "empty_args")]
    pub args: Value,
}
fn empty_args() -> Value {
    json!({})
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Recipe {
    pub version: u32,
    #[serde(default)]
    pub parameters: Map<String, Value>,
    #[serde(default)]
    pub seed: u64,
    pub calls: Vec<Call>,
}

fn resolve(value: &Value, params: &Map<String, Value>) -> Result<Value> {
    match value {
        Value::Object(o) if o.contains_key("$param") => {
            if o.len() != 1 {
                bail!("parameter references must contain only $param");
            }
            let name = o["$param"].as_str().context("$param must be a string")?;
            params
                .get(name)
                .cloned()
                .with_context(|| format!("missing recipe parameter `{name}`"))
        }
        Value::Object(o) => Ok(Value::Object(
            o.iter()
                .map(|(k, v)| Ok((k.clone(), resolve(v, params)?)))
                .collect::<Result<_>>()?,
        )),
        Value::Array(a) => Ok(Value::Array(
            a.iter()
                .map(|v| resolve(v, params))
                .collect::<Result<_>>()?,
        )),
        v => Ok(v.clone()),
    }
}

impl Recipe {
    pub fn expand(self, overrides: Map<String, Value>, seed: Option<u64>) -> Result<Vec<Call>> {
        if self.version != 1 {
            bail!("unsupported recipe version {}", self.version);
        }
        let mut params = self.parameters;
        for (key, value) in overrides {
            if !params.contains_key(&key) {
                bail!("unknown recipe parameter `{key}`");
            }
            params.insert(key, value);
        }
        if params.contains_key("seed") {
            bail!("`seed` is reserved; use the recipe seed or --seed");
        }
        params.insert("seed".into(), json!(seed.unwrap_or(self.seed)));
        self.calls
            .into_iter()
            .map(|c| {
                Ok(Call {
                    tool: c.tool,
                    args: resolve(&c.args, &params)?,
                })
            })
            .collect()
    }
}

pub fn parse_jsonl(text: &str) -> Result<Vec<Call>> {
    text.lines()
        .enumerate()
        .filter(|(_, l)| !l.trim().is_empty() && !l.trim_start().starts_with("//"))
        .map(|(i, l)| serde_json::from_str(l).with_context(|| format!("line {}", i + 1)))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn typed_parameters_and_seed_are_reproducible() {
        let text = r#"{"version":1,"parameters":{"mesh":"x.glb","amount":4},"seed":42,"calls":[{"tool":"test","args":{"path":{"$param":"mesh"},"n":{"$param":"amount"},"seed":{"$param":"seed"}}}]}"#;
        let expand = || {
            serde_json::from_str::<Recipe>(text)
                .unwrap()
                .expand(Map::new(), None)
                .unwrap()
        };
        assert_eq!(expand()[0].args, json!({"path":"x.glb","n":4,"seed":42}));
        assert_eq!(expand()[0].args, expand()[0].args);
        let r: Recipe = serde_json::from_str(text).unwrap();
        assert!(r
            .expand(Map::from_iter([("typo".into(), json!(1))]), None)
            .is_err());
    }
    #[test]
    fn malformed_calls_and_missing_parameters_fail() {
        assert!(parse_jsonl("{\"tool\":\"test\",\"arg\":{}}").is_err());
        let r: Recipe = serde_json::from_value(
            json!({"version":1,"calls":[{"tool":"test","args":{"$param":"absent"}}]}),
        )
        .unwrap();
        assert!(r.expand(Map::new(), None).is_err());
    }
}
