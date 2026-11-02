extends SkeletonModifier3D
## Aim layer on top of the animation: turns the spine towards the aim (yaw / pitch spread over Spine,
## Chest, UpperChest, then the neck), and twists the hips towards the direction of travel while the
## torso keeps aiming (strafing with the forward / backward clips). Skeleton space: the character faces
## +Z, +Y up (SkeletonProfileHumanoid after the rest fixer).

var yaw := 0.0          ## rad, + = to the character's left
var pitch := 0.0        ## rad, + = up
var hip_yaw := 0.0      ## rad: legs turned this much from the facing; the spine turns back by as much
var _y := 0.0
var _p := 0.0
var _h := 0.0
const CHAIN := [["Spine", 0.3], ["Chest", 0.3], ["UpperChest", 0.25], ["Neck", 0.15]]


func _process_modification_with_delta(delta: float) -> void:
	var sk := get_skeleton()
	if sk == null:
		return
	var k := 1.0 - exp(-delta * 14.0)
	_y = lerpf(_y, yaw, k)
	_p = lerpf(_p, pitch, k)
	_h = lerpf(_h, hip_yaw, 1.0 - exp(-delta * 8.0))
	if absf(_h) > 0.001:
		_turn(sk, sk.find_bone("Hips"), Basis(Vector3.UP, _h))
	for c in CHAIN:
		var b := sk.find_bone(c[0])
		if b < 0:
			continue
		var w: float = c[1]
		var yw := _y * w - (_h if c[0] == "Spine" else 0.0)
		_turn(sk, b, Basis(Vector3.UP, yw) * Basis(Vector3.RIGHT, -_p * w))


## Rotate bone `b` by `r` in skeleton space about its own origin.
func _turn(sk: Skeleton3D, b: int, r: Basis) -> void:
	if b < 0:
		return
	var g := sk.get_bone_global_pose(b)
	var nb := r * g.basis
	var par := sk.get_bone_parent(b)
	var pb := sk.get_bone_global_pose(par).basis if par >= 0 else Basis()
	sk.set_bone_pose_rotation(b, (pb.inverse() * nb).get_rotation_quaternion())
