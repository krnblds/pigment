extends RefCounted
## Taxi game data: fares, ride-quality rules, passenger temperaments and their lines.
## All names and lines are this city's own (Hoshikawa Dynamics, MERIDIAN, Dreamlink / Noctis, UNPLUG).

const CURRENCY := "¥"
const FLAG_FARE := 600            ## on pickup
const PER_KM := 320               ## by route length, fixed when the passenger gets in
const WAIT_PER_MIN := 90          ## while stopped with a passenger aboard (traffic lights, jams)
const CRUISE_MS := 10.5           ## the speed a passenger expects on average (for the ETA)
const ETA_SLACK_S := 25.0
const HARSH_G := 0.55             ## horizontal g above this upsets the passenger
const PICKUP_STOP_KMH := 4.0      ## slower than this next to the passenger to let them in
const PICKUP_RANGE_M := 8.0
const DROP_RANGE_M := 14.0

## Temperaments: how much time and comfort matter, how big a tip can get.
const MOODS := {
	"hurry":   {"time": 1.6, "comfort": 0.5, "tip": 0.35, "label": "IN A HURRY"},
	"calm":    {"time": 0.6, "comfort": 1.0, "tip": 0.20, "label": "EASYGOING"},
	"fragile": {"time": 0.5, "comfort": 1.8, "tip": 0.30, "label": "NERVOUS"},
	"thrill":  {"time": 1.2, "comfort": -0.4, "tip": 0.40, "label": "THRILL SEEKER"},
}

## Citizen archetype (tools/npc/recipes.py) -> likely temperaments.
const ARCHETYPE_MOODS := {
	"salaryman": ["hurry", "hurry", "calm"], "courier": ["hurry", "thrill"], "student": ["thrill", "calm"],
	"elder": ["fragile", "calm"], "nightlife": ["thrill", "calm", "fragile"], "worker": ["calm", "hurry"],
	"street": ["thrill", "calm"], "techwear": ["hurry", "calm"],
}

const PICKUP_LINES := {
	"hurry": ["{dest}. My MERIDIAN score drops if I'm late again.", "{dest}, fast. The board meeting started without me.",
		"Just get me to {dest}. Take the expressway if you have to."],
	"calm": ["{dest}, please. No rush.", "Evening. {dest}, whenever you're ready.", "{dest}. Nice night for rain, isn't it?"],
	"fragile": ["{dest}... gently, please. I just came off a Noctis lease.", "{dest}. Please don't drive like the last one.",
		"Could you take me to {dest}? Slowly. My head's still in someone else's dream."],
	"thrill": ["{dest}! Make it fun.", "{dest}. Bet you can't do it before the light changes.", "Yo, {dest}. Floor it."],
}
const DROP_LINES := {
	"good": ["Perfect. Keep the change.", "That's the smoothest ride I've had all week.", "Thanks, driver. I'll ask for you again."],
	"ok": ["Thanks.", "Here's fine.", "Okay. That'll do."],
	"bad": ["I'm reporting that to MERIDIAN.", "Never again.", "Did you get your licence from a vending machine?"],
}
const COMPLAINTS := {
	"hurry": ["Come on, come on.", "Is this the scenic route?", "Faster, please!"],
	"calm": ["Easy there.", "Whoa."],
	"fragile": ["Please! Slow down!", "I'm going to be sick.", "Gently!"],
	"thrill": ["Ha! Again!", "Now we're talking!"],
}
const CRASH_LINES := ["Hey! Watch it!", "Are you insane?!", "That's coming out of your tip."]


static func pick(arr: Array, rng: RandomNumberGenerator) -> String:
	return String(arr[rng.randi() % arr.size()]) if not arr.is_empty() else ""


static func mood_for(archetype: String, rng: RandomNumberGenerator) -> String:
	var opts: Array = ARCHETYPE_MOODS.get(archetype, ["calm", "hurry"])
	return String(opts[rng.randi() % opts.size()])


## Payout for a finished ride. route_m: route length at pickup; t: seconds driven; wait_s: seconds stopped;
## discomfort: accumulated harsh-driving score (0 = perfect); crashes: impacts; peds: pedestrians hit.
static func settle(route_m: float, t: float, wait_s: float, discomfort: float, crashes: int, peds: int, mood: String) -> Dictionary:
	var m: Dictionary = MOODS.get(mood, MOODS.calm)
	var fare := FLAG_FARE + int(round(route_m / 1000.0 * PER_KM)) + int(round(wait_s / 60.0 * WAIT_PER_MIN))
	var eta := route_m / CRUISE_MS + ETA_SLACK_S
	var lateness := clampf((t - eta) / maxf(eta, 1.0), -0.5, 2.0)       # <0 early, >0 late
	var stars := 5.0
	stars -= maxf(lateness, 0.0) * 2.0 * float(m.time)
	stars += clampf(-lateness, 0.0, 0.3) * 2.0 * float(m.time)          # early helps a little
	stars -= discomfort * 0.6 * float(m.comfort)
	stars -= crashes * 0.8 + peds * 2.5
	stars = clampf(stars, 1.0, 5.0)
	var tip := 0
	if stars >= 3.5:
		tip = int(round(fare * float(m.tip) * (stars - 3.0) / 2.0))
	return {"fare": fare, "tip": tip, "stars": snappedf(stars, 0.1), "eta": eta, "lateness": lateness,
		"total": fare + tip}
