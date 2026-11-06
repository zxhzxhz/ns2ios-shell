# Lyrica2 Stars align (續陽春白雪 結星諧調) 1.4.0: CheckArea_Word.Update's platform dispatch, keyed by main's NSO build ID.
#
# The play scene judges touch on two code paths, chosen by Application.platform (the switch at main+0x162cbb8):
#   platform 8 (iPhonePlayer) / 11 (Android) -> the UnityEngine.Input.touches path (Began -> RayCheckNote, Moved ->
#   the drag/arrow sweep, Ended -> CheckHoldNoteEnd);
#   platform 32 (Switch)                     -> NSButtonUpdate() + NS_Touch/NSTouchesUpdate(), the game's own nn::hid
#   reader (NSToucheHit dispatches on TouchState.attributes by equality: 1 = Start, 2 = End, 0 = held).
# The second path cannot work on this host: dm/host/hle_touch.c reports each finger's Start (and End) once and hands
# out a single state per GetTouchScreenStates call, so whichever reader polls first takes the edge. Unity's own input
# poll runs before any Update and takes it, and the game's judgement then only ever sees attributes 0: taps, holds,
# double notes and drag starts never register (a finger that stays down still moves the DragCheckArea colliders, so
# only presence-based judging reacts). The Input.touches path derives Began / Moved / Ended from finger presence in
# Unity itself and needs no attribute edge, and it is the path the game ships for touch devices.
# The cut makes the dispatch take the Input.touches path on every platform (b 0x162cbfc from main+0x162cbbc, the
# 'cmp w0, #8'). Cost: NSButtonUpdate() is skipped in the play scene, so judged controller buttons (the arrow notes'
# right stick, NSButtonHit) stop working there; touch play is unaffected.
CUTS = {
    '039d9876893e1136ab5233277f7a8015': [
        (0x162CBBC, '1f200071', '10000014', 'CheckArea_Word.Update: always take the Unity Input.touches path (cmp w0,#8 -> b main+0x162be7c)'),
    ],
}

# Whether a general rule could replace these patches (dm/tools/docs_patches.py lists it in docs/agents/game-patches.md)
GENERALIZE = "No: the cut depends on this game's platform dispatch and on the host's one-shot touch attributes; the right fix is the host keeping a short touch-state history (hle_touch.c touch_fill_n)"
