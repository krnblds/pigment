extends RefCounted
## Words for the Waker cases: the memory archetypes, the fragments a woken sleeper holds, MERIDIAN
## dispatch / radio lines in three tones, the UNPLUG band, and the vignettes that piece together whose
## memories are being leased. All original to this city (tools/make_story_decals.py has the world).
##
## The thread: Dreamlink's leased memories are not donated. They are cut from the Noctis wards in the
## Hill District, where people who sold "one night of sleep" have not woken for years. The oldest ward,
## bed 0-0-1, is Ayane Kuroda, a Hoshikawa systems engineer who helped build MERIDIAN's scoring and
## asked to have her own score explained.

const ARCHETYPES := {
	"parent": {
		"title": "THE SEARCH", "echo": "ECHO: A PARENT'S SEARCH", "look": "parent",
		"brief": "Calm, searching. Approach slowly, weapon away, stay where they can see you.",
		"memory": "A parent in a market crowd, calling a name. The child is never there.",
		"lines": ["Hana? Hana, where did you go?", "She was holding my sleeve...", "Have you seen a girl in a yellow coat?",
			"The lanterns were lit. It was right here.", "Hana, it's late, we have to go home."],
		"pay": 380, "wake_time": 3.5,
	},
	"soldier": {
		"title": "THE TOUR", "echo": "ECHO: A SOLDIER'S TOUR", "look": "soldier",
		"brief": "Armed. Sees you as a hostile patrol. Stun or EMP, then wake. Killing them fails the case.",
		"memory": "A border checkpoint in sleet. Sandbags, a radio that only plays static, orders that never change.",
		"lines": ["Contact! Patrol, two o'clock!", "Hold the line, hold the line.", "Nobody crosses tonight.",
			"Radio's dead. Radio's always dead.", "Get down!"],
		"pay": 620, "wake_time": 3.0,
	},
	"climber": {
		"title": "THE ASCENT", "echo": "ECHO: A CLIMBER'S LAST ASCENT", "look": "climber",
		"brief": "Runs the scaffolds in the memory's route. Keep up, corner them at the top, then go in calm.",
		"memory": "A free-climber's last night on the old Tenjin scaffolds, before the towers went up over them.",
		"lines": ["Just one more level.", "Don't look down. Never look down.", "The view's better at the top.",
			"They're taking the scaffolds down tomorrow."],
		"pay": 520, "wake_time": 3.0,
	},
	"courier": {
		"title": "THE LAST RUN", "echo": "ECHO: A COURIER'S LAST RUN", "look": "courier",
		"brief": "Driving the memory's delivery route. Box them in with the cruiser or stall the car with an EMP.",
		"memory": "A night courier's final route, the one that ended at a closed bridge in the rain.",
		"lines": ["Twelve minutes. I can make it in twelve.", "Parcel for Sector Nine, signature required.",
			"The bridge is open tonight. It's open.", "Don't brake. Don't brake."],
		"pay": 560, "wake_time": 3.0,
	},
	"swarm": {
		"title": "THE LAST TRAIN", "echo": "ECHO: THE LAST TRAIN (SHARED)", "look": "swarm",
		"brief": "Several sleepers in one memory. Startle one and you startle them all. Wake them one by one.",
		"memory": "A crowded platform, the last train out before the line was sold. Everyone is still waiting.",
		"lines": ["It's late. It's always late.", "Mind the gap.", "We'll be home soon.", "Don't push, there's room."],
		"pay": 300, "wake_time": 2.5,
	},
}

## What the woken sleeper is holding: one per archetype per case (picked by case number).
const FRAGMENTS := {
	"parent": ["a yellow coat sleeve, rain-dark, and the smell of grilled squid", "a child's laugh under paper lanterns",
		"a hand letting go in a crowd"],
	"soldier": ["the static on the radio, and under it a woman humming", "a checkpoint log with every page the same date",
		"sleet on sandbags and a promise to write home"],
	"climber": ["the city from the top of a scaffold before the towers", "chalk on cold steel, and nobody watching",
		"the last rung, and choosing not to jump"],
	"courier": ["a parcel addressed to a ward in the Hill District", "a route map with the bridge still drawn on it",
		"rain on a windscreen and a signature that never came"],
	"swarm": ["a ticket for a train that no longer runs", "a crowded platform, warm, everyone going home",
		"the announcement nobody heard to the end"],
}

## The UNPLUG thread, revealed one vignette per fragment you let a sleeper keep.
const VIGNETTES := [
	"The fragment is warm. It isn't the sleeper's: there's a second set of memories folded under it, older, filed with a ward number.\nNOCTIS WARD 0-0-1.",
	"UNPLUG band, crackling:\n\"Leased memories don't come from volunteers, Waker. They come from the wards. Ask Hoshikawa how long ward 0-0-1 has been asleep.\"",
	"A name surfaces under the static: AYANE KURODA. Hoshikawa systems engineer. Last score on record: 911. Then the record is sealed.",
	"Kuroda helped write MERIDIAN's scoring. Her last request on file: \"Explain my score to me.\" The reply was a Noctis sleep voucher.",
	"Eleven years in ward 0-0-1. Her memories have been cut into four thousand leases. Every sleepwalker you've woken was living a piece of someone, and some of them were living her.",
	"UNPLUG band:\n\"We're going into the Hill District wards. We don't need you to help. We need you to not report what you find tonight.\"",
	"The last fragment is hers, unshared: an office at night, the scoring model on the screen, and a cursor over a line she never got to delete.",
]

const RADIO := {
	"dispatch": {
		"corporate": ["MERIDIAN: Sleeper signal degraded in %s. Waker, restore the citizen before dawn. Your diligence is noted.",
			"MERIDIAN: Dreamlink lease desync, %s. Recover the asset. Efficiency is a virtue."],
		"neutral": ["DISPATCH: Sleepwalker reported, %s. Signal is rough. Find them and bring them back.",
			"DISPATCH: Another one didn't come back from a lease. %s. You're up, Waker."],
		"cold": ["MERIDIAN: %s. A sleeper is loose. Your recent conduct is under review. Do not deviate.",
			"MERIDIAN: Waker 4C-1187, your compliance index is low. Recover the sleeper in %s. Report everything."],
	},
	"located": ["DISPATCH: Echo confirmed. That's %s. You know how this one goes.", "MERIDIAN: Memory archetype identified: %s."],
	"woken": ["DISPATCH: Sleeper's back. Nice work.", "MERIDIAN: Citizen restored. Awaiting your report."],
	"failed_kill": ["MERIDIAN: Citizen terminated. This is a failure of procedure. Your score has been adjusted.",
		"DISPATCH: ...they're gone, Waker. That's not what we do."],
	"failed_dawn": ["MERIDIAN: Dawn. The lease has closed. Sleeper unrecoverable.", "DISPATCH: Sun's up. We lost that one to the lease."],
	"reported": ["MERIDIAN: Fragment wiped. Your cooperation strengthens the city.", "MERIDIAN: Report filed. Credit transferred."],
	"kept": ["MERIDIAN: Report incomplete. Noted.", "MERIDIAN: Fragment missing from your report. Discrepancy logged."],
	"unplug": ["UNPLUG: Thanks for looking the other way, Waker.", "UNPLUG: Every fragment you leave them is a piece of someone coming home.",
		"UNPLUG: Keep your scanner on the Hill District. Something's moving in the wards."],
	"audit": ["MERIDIAN: Compliance audit in progress. Remain where you are.", "HOSHIKAWA AUDIT: Drone dispatched to your position."],
	"audit_clear": ["MERIDIAN: Audit complete. No action.", "AUDIT: Lost contact with the officer. Flag closed."],
	"audit_flag": ["HOSHIKAWA AUDIT: Officer flagged. Penalty applied.", "MERIDIAN: Audit findings filed against you."],
	"dawn": ["MERIDIAN: Dawn. Shift over. Rest is a resource.", "DISPATCH: That's sunrise. Go home, Waker."],
	"night": ["DISPATCH: New night, Waker. Rain's coming in.", "MERIDIAN: Night shift begins. Dreamlink load nominal."],
}

const DISTRICTS := ["HARBOUR", "KABUKI ROW", "HILL DISTRICT", "TENJIN", "SECTOR 4", "SECTOR 7", "SECTOR 9", "OLD MARKET", "BAYSIDE", "YOIMACHI"]
const NAMES := ["KANO M.", "SATO R.", "MIKA T.", "IDE J.", "ONO K.", "FUJI A.", "NARA S.", "HAYASHI E.", "MORI T.", "KUDO Y.",
	"TANI H.", "SERA N."]
