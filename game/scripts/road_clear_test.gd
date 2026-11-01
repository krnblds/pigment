extends Node
## --road-clear-test[=<out.json>]: sweeps a car-sized box along every lane of every road in
## world.json (bridge decks and approaches included) and reports anything the box hits
## between 0.4 m and 1.9 m above the lane, plus points where the ground under the lane is
## not road (terrain or another mesh poking through). Headless OK.

var main: Node
const STEP := 2.0
const HALF := Vector3(0.75, 0.55, 1.0)      # a car's width / height band / length, halved

func _ready() -> void:
	_run.call_deferred()


static func _g(p: Array) -> Vector3:
	return Vector3(p[0], p[2], -p[1])


func _run() -> void:
	await get_tree().physics_frame
	var wp := "res://assets/world/world.json"
	var w = JSON.parse_string(FileAccess.get_file_as_string(wp))
	var space := get_viewport().get_world_3d().direct_space_state
	var shape := BoxShape3D.new()
	shape.size = HALF * 2.0
	var q := PhysicsShapeQueryParameters3D.new()
	q.shape = shape
	q.collide_with_areas = false
	var ray := PhysicsRayQueryParameters3D.new()
	var hits := {}
	var ground := {}
	var examples := []
	var samples := 0
	var last_stream := Vector3(1e9, 0, 0)
	var car_rid: RID = main.car.get_rid() if main.car else RID()
	if car_rid.is_valid():
		q.exclude = [car_rid]
		ray.exclude = [car_rid]
	for r in w.roads:
		var pts: Array = r.points
		var deck: Array = r.get("deck", [])
		for lane in r.lanes:
			if lane.get("kind", "drive") != "drive":
				continue
			var off := float(lane.offset)
			var s := 0.0
			for i in range(pts.size() - 1):
				var a := _g(pts[i])
				var b := _g(pts[i + 1])
				var seg := b - a
				var L := seg.length()
				if L < 0.01:
					continue
				var t := seg / L
				var side := Vector3.UP.cross(t).normalized()
				var on_deck := i < deck.size() and bool(deck[i])
				var u := fmod(s, STEP)
				while u < L:
					var c := a + t * u + side * off
					if c.distance_to(last_stream) > 80.0:
						main.town._stream_collision(Vector2(c.x, c.z), true)   # collision lives within 300 m of the car
						if main.has_method("stream_now"):
							main.stream_now(c)
						last_stream = c
						await get_tree().physics_frame
						await get_tree().physics_frame
					samples += 1
					# 1) anything in the car's body band above the lane
					q.transform = Transform3D(Basis.looking_at(t, Vector3.UP), c + Vector3.UP * (0.4 + HALF.y))
					for h in space.intersect_shape(q, 8):
						var nm := _name(h.collider)
						if nm == "":
							continue
						hits[nm] = int(hits.get(nm, 0)) + 1
						if examples.size() < 60:
							examples.append({"road": r.id, "class": r["class"], "deck": on_deck, "hit": nm, "pos": [snappedf(c.x, 0.1), snappedf(c.y, 0.1), snappedf(c.z, 0.1)]})
					# 2) what is directly under the lane
					ray.from = c + Vector3.UP * 3.0
					ray.to = c - Vector3.UP * 3.0
					var g := space.intersect_ray(ray)
					var gn := _ground(g)
					if gn != "road":
						ground[gn] = int(ground.get(gn, 0)) + 1
						if examples.size() < 60:
							examples.append({"road": r.id, "class": r["class"], "deck": on_deck, "ground": gn, "pos": [snappedf(c.x, 0.1), snappedf(c.y, 0.1), snappedf(c.z, 0.1)],
								"ground_y": snappedf(g.position.y, 0.01) if g else null})
					u += STEP
				s += L
	var res := {"samples": samples, "body_hits": hits, "ground_not_road": ground, "examples": examples}
	print("ROADCLEAR ", JSON.stringify(res))
	var out := String(main.args.get("road-clear-test", "1"))
	if out != "1":
		var f := FileAccess.open(out, FileAccess.WRITE)
		f.store_string(JSON.stringify(res, "  "))
	get_tree().quit()


## A collider that counts as an obstacle (empty = ignore: road surfaces, the car).
func _name(c: Object) -> String:
	if c == null:
		return ""
	var nm := String(c.name)
	var cat := _cat(nm)
	if cat in ["road", "bridge_deck"]:
		return ""
	return cat + ":" + nm.trim_prefix("Col_").left(48)


func _ground(g: Dictionary) -> String:
	if g.is_empty():
		return "none"
	var nm := String(g.collider.name)
	var cat := _cat(nm)
	return "road" if cat in ["road", "bridge_deck"] else cat + ":" + nm.trim_prefix("Col_").left(40)


func _cat(nm: String) -> String:
	var key := nm.trim_prefix("Col_")
	var layout: Dictionary = main.town.layout
	if layout.has("meshes") and layout.meshes.has(key):
		var c := String(layout.meshes[key].get("cat", "other"))
		if c == "bridge" and (key.contains("deck") or key.contains("Deck") or key.begins_with("Road") or key.begins_with("Bridge_")):
			return "bridge_deck"
		return c
	if nm.begins_with("Road") or nm.contains("Junction") or nm.begins_with("JDecals"):
		return "road"
	if nm.contains("Terrain") or nm.contains("terrain") or nm.contains("Height"):
		return "terrain"
	return "other"
