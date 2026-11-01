extends RefCounted
## Vehicle physics parameters: class defaults (data/vehicles/classes.json) <- values derived from the
## car contract json (car.json / the fleet's <id>.json: mass, centre of mass, wheels, dimensions,
## suspension suggestion) <- the vehicle's own data/vehicles/<id>.json.  Everything is plain
## Dictionaries so a tuning json can override any single value.

const CLASSES := "res://data/vehicles/classes.json"
const DIR := "res://data/vehicles/"


static func _read(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		return {}
	var d = JSON.parse_string(FileAccess.get_file_as_string(path))
	return d if d is Dictionary else {}


## b over a, recursively (dictionaries merge, anything else replaces).
static func merge(a: Dictionary, b: Dictionary) -> Dictionary:
	var out := a.duplicate(true)
	for k in b:
		if String(k).begins_with("_"):
			continue
		if out.has(k) and out[k] is Dictionary and b[k] is Dictionary:
			out[k] = merge(out[k], b[k])
		else:
			out[k] = b[k] if not (b[k] is Dictionary or b[k] is Array) else b[k].duplicate(true)
	return out


## spec: the car contract json.  id: the vehicle id (data/vehicles/<id>.json), "" = from the spec.
static func build(spec: Dictionary, id := "") -> Dictionary:
	if id == "":
		id = String(spec.get("id", "tsubame"))
	var own := _read(DIR + id + ".json")
	var classes := _read(CLASSES)
	var cls := String(own.get("class", spec.get("class", "sedan")))
	var base: Dictionary = classes.get("sedan", {})
	if cls != "sedan" and classes.has(cls):
		base = merge(base, classes[cls])
	var p := merge(base, _derived(spec, base))
	p = merge(p, own)
	p["id"] = id
	p["class"] = cls
	_finish(p)
	return p


## What the car contract tells us about this vehicle.
static func _derived(spec: Dictionary, base: Dictionary) -> Dictionary:
	var d := {}
	var mass := float(spec.get("mass_kg", spec.get("mass", 1300.0)))
	var r := float(spec.get("wheel_radius", 0.33))
	var track := float(spec.get("track", 1.55))
	var wb := float(spec.get("wheelbase", 2.6))
	var dims: Dictionary = spec.get("dimensions", {})
	var length := float(dims.get("length", wb + 1.8))
	var width := float(dims.get("width_body", dims.get("width", track + 0.25)))
	if width > track + 0.6:          # "width" in the fleet jsons includes the mirrors
		width = track + 0.25
	var height := float(dims.get("height_roof", dims.get("height", 1.45)))
	var com: Array = spec.get("center_of_mass", [0.0, 0.5, 0.0])
	d["mass"] = mass
	d["center_of_mass"] = [float(com[0]), float(com[1]), float(com[2])]
	d["wheel_radius"] = r
	d["wheel_width"] = float(spec.get("wheel_width", 0.2))
	var wp: Dictionary = spec.get("wheel_positions", {})
	var wheels := {}
	for wn in ["Wheel_FL", "Wheel_FR", "Wheel_RL", "Wheel_RR"]:
		if wp.has(wn):
			wheels[wn] = wp[wn]
		else:
			wheels[wn] = [track * 0.5 * (1.0 if wn.ends_with("L") else -1.0), r, wb * 0.5 * (1.0 if wn[6] == "F" else -1.0)]
	d["wheels"] = wheels
	d["dimensions"] = {"length": length, "width": width, "height": height}
	# yaw / pitch / roll inertia of a car-like mass distribution (measured cars: Iyaw ~ m * a * b)
	var a := absf(float(wheels.Wheel_FL[2]) - float(com[2]))
	var b := absf(float(wheels.Wheel_RL[2]) - float(com[2]))
	d["inertia"] = [mass * (a * b) * 0.95, mass * (a * b) * 1.05, mass * (width * width + height * height) / 12.0 * 1.15]
	# the rest of the body depends on the class defaults too (_finish)
	var sus: Dictionary = spec.get("suspension_suggestion", {})
	if sus.has("travel"):
		d["suspension"] = {"bump": clampf(float(sus.travel) * 0.8, 0.07, 0.13)}
	return d


## Values that depend on the merged set (loads, spring rates, brake torque, frontal area).
static func _finish(p: Dictionary) -> void:
	var g := 9.81
	var mass := float(p.mass)
	var com: Array = p.center_of_mass
	var zf := float(p.wheels.Wheel_FL[2])
	var zr := float(p.wheels.Wheel_RL[2])
	var wb := zf - zr
	var front_share := (float(com[2]) - zr) / wb
	p["front_share"] = front_share
	var sus: Dictionary = p.suspension
	var static_f := mass * g * front_share * 0.5          # per wheel
	var static_r := mass * g * (1.0 - front_share) * 0.5
	sus["static_front"] = static_f
	sus["static_rear"] = static_r
	# spring rate from the ride frequency of the corner's sprung mass (wheel rate)
	sus["k_front"] = float(sus.get("k_front", (static_f / g) * pow(TAU * float(sus.ride_hz_front), 2.0)))
	sus["k_rear"] = float(sus.get("k_rear", (static_r / g) * pow(TAU * float(sus.ride_hz_rear), 2.0)))
	# droop: just past the static sag, so a lifted wheel hangs with no spring force left
	sus["droop_front"] = static_f / float(sus.k_front) + float(sus.droop_extra)
	sus["droop_rear"] = static_r / float(sus.k_rear) + float(sus.droop_extra)
	for ax in ["front", "rear"]:
		var k := float(sus["k_" + ax])
		var m := (static_f if ax == "front" else static_r) / g
		var cc := 2.0 * sqrt(k * m)
		sus["c_bump_" + ax] = cc * float(sus.damping_bump)
		sus["c_rebound_" + ax] = cc * float(sus.damping_rebound)
	var br: Dictionary = p.brakes
	var r := float(p.wheel_radius)
	br["max_torque"] = float(br.get("max_torque", mass * g * float(br.max_decel_g) * r))
	var aero: Dictionary = p.aero
	var dims: Dictionary = p.dimensions
	aero["area"] = float(aero.get("area", float(dims.width) * float(dims.height) * float(aero.area_scale)))
	var tyres: Dictionary = p.tyres
	for ax in ["front", "rear"]:
		var t: Dictionary = tyres[ax]
		t["peak_slip_angle"] = tan(deg_to_rad(float(t.peak_slip_angle_deg)))
		t["load_ref"] = static_f if ax == "front" else static_r
	var eng: Dictionary = p.engine
	var curve: Array = eng.torque_curve
	var peak := 0.0
	for pt in curve:
		peak = maxf(peak, float(pt[1]))
	eng["peak_torque"] = peak
