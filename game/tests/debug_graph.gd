extends SceneTree
## Dump a lane graph: godot --headless --path game --script res://tests/debug_graph.gd -- <world json> [junction name]
func _init() -> void:
	var a := OS.get_cmdline_user_args()
	var G = preload("res://scripts/traffic/lane_graph.gd").new()
	G.build_from_world(JSON.parse_string(FileAccess.get_file_as_string(a[0])))
	print(JSON.stringify(G.summary()))
	if a.size() > 1:
		for J in G.junctions:
			if J.name != a[1]:
				continue
			print("control ", J.control, " approaches ", J.approaches.map(func(x): return [G.roads[x.road].name, x.major]))
			for ci in J.connectors:
				var c = G.lanes[ci]
				print(ci, " ", c.name, " turn ", c.turn, " rank ", c.rank, " conflicts ", Array(c.conflicts).map(func(k): return G.lanes[k].name))
	quit()
