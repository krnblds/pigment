extends RefCounted
func run(ct) -> void:
	await ct.get_tree().process_frame
