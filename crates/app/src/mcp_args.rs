//! Check MCP tool arguments against the tool's JSON schema before running
//! it, so a bad call fails with a message that names the argument (unknown
//! key, wrong type, value outside an enum, missing required field) instead
//! of being silently ignored or failing deep inside the tool.
//!
//! Supports the subset of JSON Schema the Pigment tools use: `type` (a name
//! or a list of names), `enum`, `properties`, `required`, `items`,
//! `additionalProperties: false`, `minimum` / `maximum`.

use serde_json::Value;

/// Validate `args` for `tool` against its `inputSchema`.
pub fn validate(tool: &str, schema: &Value, args: &Value) -> Result<(), String> {
    let empty = Value::Object(Default::default());
    let args = if args.is_null() { &empty } else { args };
    check(schema, args, "").map_err(|e| format!("{tool}: {e}"))
}

fn type_ok(t: &str, v: &Value) -> bool {
    match t {
        "string" => v.is_string(),
        "boolean" => v.is_boolean(),
        "object" => v.is_object(),
        "array" => v.is_array(),
        "null" => v.is_null(),
        "number" => v.is_number(),
        // strict: the tools read integers with as_u64, which ignores 4096.0
        "integer" => v.is_i64() || v.is_u64(),
        _ => true,
    }
}

fn describe(v: &Value) -> String {
    let s = v.to_string();
    if s.len() > 60 {
        format!("{}...", &s[..57])
    } else {
        s
    }
}

fn kind(v: &Value) -> &'static str {
    match v {
        Value::Null => "null",
        Value::Bool(_) => "a boolean",
        Value::Number(n) if n.is_f64() => "a number",
        Value::Number(_) => "an integer",
        Value::String(_) => "a string",
        Value::Array(_) => "an array",
        Value::Object(_) => "an object",
    }
}

fn name(path: &str) -> String {
    if path.is_empty() {
        "arguments".into()
    } else {
        format!("`{path}`")
    }
}

fn check(schema: &Value, v: &Value, path: &str) -> Result<(), String> {
    let types: Vec<&str> = match schema.get("type") {
        Some(Value::String(t)) => vec![t.as_str()],
        Some(Value::Array(ts)) => ts.iter().filter_map(Value::as_str).collect(),
        _ => vec![],
    };
    if !types.is_empty() && !types.iter().any(|t| type_ok(t, v)) {
        return Err(format!("{} must be {}, got {} ({})", name(path), types.join(" or "), kind(v), describe(v)));
    }
    if let Some(Value::Array(opts)) = schema.get("enum") {
        if !opts.contains(v) {
            let list: Vec<String> = opts.iter().map(|o| o.as_str().map(String::from).unwrap_or_else(|| o.to_string())).collect();
            return Err(format!("{} = {} is not one of: {}", name(path), describe(v), list.join(", ")));
        }
    }
    if let Some(x) = v.as_f64() {
        if let Some(lo) = schema.get("minimum").and_then(Value::as_f64) {
            if x < lo {
                return Err(format!("{} = {x} is below the minimum {lo}", name(path)));
            }
        }
        if let Some(hi) = schema.get("maximum").and_then(Value::as_f64) {
            if x > hi {
                return Err(format!("{} = {x} is above the maximum {hi}", name(path)));
            }
        }
    }
    let join = |k: &str| if path.is_empty() { k.to_string() } else { format!("{path}.{k}") };
    if let (Some(obj), Some(props)) = (v.as_object(), schema.get("properties").and_then(Value::as_object)) {
        for (k, val) in obj {
            match props.get(k) {
                Some(ps) => check(ps, val, &join(k))?,
                None if schema.get("additionalProperties") == Some(&Value::Bool(false)) => {
                    let mut known: Vec<&str> = props.keys().map(String::as_str).collect();
                    known.sort_unstable();
                    let hint = closest(k, &known).map(|c| format!(" (did you mean `{c}`?)")).unwrap_or_default();
                    return Err(format!("unknown argument `{}`{hint}; accepted: {}", join(k), known.join(", ")));
                }
                None => {}
            }
        }
        if let Some(Value::Array(req)) = schema.get("required") {
            for r in req.iter().filter_map(Value::as_str) {
                if !obj.contains_key(r) {
                    let d = props.get(r).and_then(|p| p.get("description")).and_then(Value::as_str).map(|d| format!(" ({d})")).unwrap_or_default();
                    return Err(format!("missing required argument `{}`{d}", join(r)));
                }
            }
        }
    }
    if let (Some(arr), Some(max)) = (v.as_array(), schema.get("maxItems").and_then(Value::as_u64)) {
        if arr.len() as u64 > max {
            return Err(format!("{} has {} items, at most {max} allowed", name(path), arr.len()));
        }
    }
    if let (Some(arr), Some(items)) = (v.as_array(), schema.get("items")) {
        for (i, x) in arr.iter().enumerate() {
            check(items, x, &format!("{}[{i}]", if path.is_empty() { "arguments" } else { path }))?;
        }
    }
    Ok(())
}

/// The known name closest to `k` (edit distance <= 3, or a prefix match).
fn closest<'a>(k: &str, known: &[&'a str]) -> Option<&'a str> {
    fn dist(a: &str, b: &str) -> usize {
        let b: Vec<char> = b.chars().collect();
        let mut prev: Vec<usize> = (0..=b.len()).collect();
        for (i, ca) in a.chars().enumerate() {
            let mut cur = vec![i + 1];
            for (j, cb) in b.iter().enumerate() {
                cur.push((prev[j] + (ca != *cb) as usize).min(prev[j + 1] + 1).min(cur[j] + 1));
            }
            prev = cur;
        }
        prev[b.len()]
    }
    let k = k.to_ascii_lowercase();
    known
        .iter()
        .map(|c| (if c.starts_with(&k) || k.starts_with(c) { 0 } else { dist(&k, c) }, *c))
        .filter(|(d, _)| *d <= 3)
        .min_by_key(|(d, _)| *d)
        .map(|(_, c)| c)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn schema() -> Value {
        json!({ "type": "object", "additionalProperties": false, "required": ["mesh"], "properties": {
            "mesh": { "type": "string", "description": "path to a .glb" },
            "resolution": { "type": "integer", "enum": [512, 1024, 2048, 4096] },
            "zoom": { "type": "number", "minimum": 0.05 },
            "points": { "type": "array", "items": { "type": "array", "items": { "type": "number" } } },
            "layer": { "type": ["string", "integer"] },
            "mask": { "type": ["string", "object", "null"], "additionalProperties": false, "properties": {
                "parts": { "type": "array", "items": { "type": "integer", "minimum": 0 } }, "invert": { "type": "boolean" } } }
        } })
    }

    #[test]
    fn good_arguments_pass() {
        let s = schema();
        validate("t", &s, &json!({ "mesh": "a.glb", "resolution": 4096, "zoom": 1.5, "points": [[0.1, 0.2]], "layer": 3, "mask": { "parts": [1, 300] } })).unwrap();
        validate("t", &s, &json!({ "mesh": "a.glb", "resolution": 2048, "layer": "Base", "mask": null })).unwrap();
        validate("t", &s, &json!({ "mesh": "a.glb", "mask": "white" })).unwrap();
    }

    #[test]
    fn errors_name_the_bad_argument() {
        let s = schema();
        let e = |a: Value| validate("new_project", &s, &a).unwrap_err();
        assert_eq!(e(json!({})), "new_project: missing required argument `mesh` (path to a .glb)");
        assert!(e(json!({ "mesh": 3 })).contains("`mesh` must be string, got an integer"), "{}", e(json!({ "mesh": 3 })));
        let r = e(json!({ "mesh": "a", "resolution": 3000 }));
        assert!(r.contains("`resolution` = 3000 is not one of: 512, 1024, 2048, 4096"), "{r}");
        let r = e(json!({ "mesh": "a", "resolutoin": 512 }));
        assert!(r.contains("unknown argument `resolutoin` (did you mean `resolution`?)"), "{r}");
        let r = e(json!({ "mesh": "a", "points": [[0.1, "x"]] }));
        assert!(r.contains("`points[0][1]` must be number"), "{r}");
        let r = e(json!({ "mesh": "a", "mask": { "parts": [1, -2] } }));
        assert!(r.contains("`mask.parts[1]` = -2 is below the minimum 0"), "{r}");
        let r = e(json!({ "mesh": "a", "mask": { "part": [1] } }));
        assert!(r.contains("unknown argument `mask.part` (did you mean `parts`?)"), "{r}");
        let r = e(json!({ "mesh": "a", "zoom": 0.0 }));
        assert!(r.contains("`zoom` = 0 is below the minimum 0.05"), "{r}");
        assert!(e(json!([1, 2])).contains("arguments must be object"));
        let r = e(json!({ "mesh": "a", "resolution": 2048.0 }));
        assert!(r.contains("`resolution` must be integer, got a number (2048.0)"), "{r}");
    }
}
