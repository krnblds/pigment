extends Node
## --taxi-test (headless OK): fare maths, a fare offered on a reachable kerb with a route, boarding when
## the car stops beside the passenger, a ride to the destination, payout + rating, save round trip.
## Exit code 0 = pass.   --taxi-shots=<dir> (windowed): the same run, saving screenshots on the way.

const Data := preload("res://scripts/taxi/taxi_data.gd")

var main: Node3D
var res := {}
var fails: Array = []
var shots := ""


func _shot(name: String) -> void:
	if shots == "":
		return
	await _wait(1.5)
	await RenderingServer.frame_post_draw
	DirAccess.make_dir_recursive_absolute(shots)
	get_viewport().get_texture().get_image().save_png(shots.path_join(name + ".png"))


func _ready() -> void:
	_run.call_deferred()


func _check(n: String, ok: bool, info = null) -> void:
	res[n] = ok if info == null else [ok, info]
	if not ok:
		fails.append("%s %s" % [n, str(info)])


func _wait(s: float) -> void:
	var t := 0.0
	while t < s:
		await get_tree().physics_frame
		t += 1.0 / Engine.physics_ticks_per_second


## Park the car on the road lane nearest p, facing along it.
func _park_at(p: Vector3) -> void:
	var tx = main.taxi
	var r: Array = tx.graph.nearest(p, 40.0, true)
	var l = tx.graph.lanes[r[0]]
	var s := clampf(float(r[1]), 0.0, l.length)
	var q: Vector3 = l.pos_at(s)
	var dir: Vector3 = l.dir_at_seg(l.seg_at(s, 0))
	main.stream_now(q)
	if main.town and main.town.has_method("ensure_collision"):
		main.town.ensure_collision(q, 40.0)
	await get_tree().physics_frame
	main.car.place(Transform3D(Basis.looking_at(-dir, Vector3.UP), q + Vector3.UP * 0.6))
	await _wait(1.2)


func _run() -> void:
	var t0 := Time.get_ticks_msec()
	shots = String(main.args.get("taxi-shots", ""))
	# 1. fare maths
	var perfect := Data.settle(3000.0, 3000.0 / Data.CRUISE_MS, 0.0, 0.0, 0, 0, "calm")
	var late := Data.settle(3000.0, 3000.0 / Data.CRUISE_MS * 2.5, 0.0, 0.0, 0, 0, "hurry")
	var rough := Data.settle(3000.0, 3000.0 / Data.CRUISE_MS, 0.0, 3.0, 2, 0, "fragile")
	var thrill := Data.settle(3000.0, 3000.0 / Data.CRUISE_MS, 0.0, 2.0, 0, 0, "thrill")
	_check("fare_distance", int(perfect.fare) == Data.FLAG_FARE + int(round(3.0 * Data.PER_KM)), perfect.fare)
	_check("perfect_5_stars_and_tip", float(perfect.stars) >= 4.9 and int(perfect.tip) > 0, perfect)
	_check("late_hurts_hurry", float(late.stars) < 3.0, late.stars)
	_check("rough_hurts_fragile", float(rough.stars) <= 2.0 and int(rough.tip) == 0, rough.stars)
	_check("thrill_likes_rough", float(thrill.stars) >= 4.9, thrill.stars)
	# 2. a live fare
	var tx = main.taxi
	tx.auto_next = false
	var t := 0.0
	while tx.graph == null and t < 30.0:
		tx._graph()
		await _wait(0.5)
		t += 0.5
	_check("lane_graph", tx.graph != null)
	if tx.graph == null:
		_finish(t0)
		return
	await _wait(1.0)
	var offered := false
	for k in 5:
		if tx.new_fare():
			offered = true
			break
		await _wait(0.2)
	_check("fare_offered", offered and tx.state == tx.TO_PICKUP and tx.passenger != null)
	if not offered:
		_finish(t0)
		return
	_check("pickup_route", tx.route_pts.size() >= 2, tx.route_pts.size())
	if main.cam:
		main.cam.snap()
	await _shot("taxi_pickup_route")
	# drive up beside them (teleport onto the kerb lane next to the passenger) and stop
	await _park_at(tx.pickup_road)
	if shots != "":
		var c := Camera3D.new()
		main.add_child(c)
		c.global_position = tx.pickup_pos + (tx.pickup_road - tx.pickup_pos).normalized() * -3.0 + Vector3.UP * 1.8
		c.look_at(tx.pickup_road + Vector3.UP * 0.8)
		c.make_current()
		await _shot("taxi_hail")
		main.cam.make_current()
		c.queue_free()
	t = 0.0
	while tx.state != tx.RIDING and t < 10.0:
		await _wait(0.2)
		t += 0.2
	_check("boarded", tx.state == tx.RIDING, tx.STATE_NAMES[tx.state])
	if tx.state != tx.RIDING:
		_finish(t0)
		return
	_check("destination_named", String(tx.dest_name) != "", tx.dest_name)
	_check("ride_route", tx.route_pts.size() >= 2 and tx.route_m > 300.0, tx.route_m)
	await _shot("taxi_riding")
	# arrive on time: fake the clock to a punctual ride, then park at the address
	tx.ride_t = tx.route_m / Data.CRUISE_MS * 0.9
	var got := {}
	tx.fare_finished.connect(func(r): got.merge(r))
	await _park_at(tx.dest_road)
	t = 0.0
	while got.is_empty() and t < 10.0:
		await _wait(0.2)
		t += 0.2
	_check("dropped_off", not got.is_empty())
	await _shot("taxi_result")
	if not got.is_empty():
		_check("paid", int(got.total) >= Data.FLAG_FARE, got.total)
		_check("rating_range", float(got.stars) >= 1.0 and float(got.stars) <= 5.0, got.stars)
		_check("stats", int(tx.stats.fares) == 1 and int(tx.stats.earned) == int(got.total), tx.stats)
	t = 0.0
	while tx.state != tx.WAITING and t < 6.0:
		await _wait(0.2)
		t += 0.2
	_check("walked_off", tx.state == tx.WAITING and tx.passenger == null)
	# 3. save round trip
	tx.save_path = "user://taxi_test.json"
	tx._save()
	var before: Dictionary = tx.stats.duplicate()
	tx.stats = {"earned": 0, "fares": 0, "stars_sum": 0.0, "best_tip": 0}
	tx._load()
	_check("save_round_trip", int(tx.stats.earned) == int(before.earned) and int(tx.stats.fares) == int(before.fares))
	DirAccess.remove_absolute(ProjectSettings.globalize_path("user://taxi_test.json"))
	_finish(t0)


func _finish(t0: int) -> void:
	res["ms"] = Time.get_ticks_msec() - t0
	res["fails"] = fails
	print("TAXITEST ", JSON.stringify(res))
	print("TAXITEST %s: %d failures" % ["PASS" if fails.is_empty() else "FAIL", fails.size()])
	get_tree().quit(0 if fails.is_empty() else 1)
