extends Node
## (stub, replaced below)
var waker: Node
var prof_us := 0.0
var radio: Array = []
var unplug := 0
var credits := 0
var choice_pending := false
var scan_active := false
var scan_strength := 0.0
var scan_dir := Vector3.ZERO
var scan_pulse_t := 0.0
var sync := 0.0
func handle_input(_e) -> bool: return false
func dispatch_text() -> String: return ""
func choice_text() -> String: return ""
func prompt() -> String: return ""
func marker_position(): return null
func marker_is_sleeper() -> bool: return false
func marker_label() -> String: return ""
func area_radius_px(_c, _v) -> float: return 0.0
func sync_target(): return null
