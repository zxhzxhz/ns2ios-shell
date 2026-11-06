# GROOVE COASTER FUTURE PERFORMERS (01003F80212D8000), Unity 2022.3.62f1, provisional profile written on Windows.
#
# One bug of the game's own code, met on iOS: when the first save commits, a dynamically sized UI strip render target
# (measured 1024x32, 1024x200 and 1792x80 RGBA8 over three runs) is destroyed while the draws that still name it are
# submitted. The host survives its half -- hle_nvn.c's tex_snap logs the dead object and reads it again at submit, and
# nvnTextureGetTarget answers a 1x1 default for the null handle (private shell, "a texture getter was asked about a NULL
# handle") -- but Unity's own code then dereferences the null wrapper:
#
#   00acd8f4  bl   #0xab5df0          ; Unity's handle table: id -> slot, 0 when the slot was freed
#   00acd8f8  mov  x22, x0            ; <- the only one of three lookups in this function with no null check
#   ...
#   00acd958  ldr  w9, [x22, #0xa4]   ; sig=11, addr=0xa4 (three runs, same instruction, same address)
#   00acd97c  ldr  w9, [x22, #0xac]   ; and eight more uses after it
#
# 0xab5df0 reads its table as table[(id >> 7)] -> slot[id & 0x3ff] and returns 0 for an empty slot, so a null here means
# "the handle was freed", not "bad id" (an id at or above 0x100000 takes the error path). The function is a render-target
# state sync: it compares three cached fields of the target with the pipeline's, sets dirty bits and calls an apply path.
# With the target already gone there is nothing to sync, so the fix is to return from the function when the lookup comes
# back empty -- what the three guarded lookups in the neighbouring function (main+0xacdac4) already do with csel.
CAVES = {
    'a11792c8cb3939bdbe691dc5913c1098': [
        # x22 = the dead render target's slot: restore the callee-saved registers from this frame (the prologue saved
        # x19-x30 at sp+0x20..0x70 and subtracted 0x80) and return, instead of running the sync on a null pointer.
        (0xacd8f8, 'f60300aa',
         ['b5000100',   # cbnz x0, +0x20        (non-zero: the original mov runs below and execution continues)
          'a94657f6',   # ldp x22, x21, [sp,#0x60]
          'a9455ff8',   # ldp x24, x23, [sp,#0x50]
          'a9474ff4',   # ldp x20, x19, [sp,#0x70]
          'a9436ffc',   # ldp x28, x27, [sp,#0x30]
          'a9427bfd',   # ldp x29, x30, [sp,#0x20]
          '910203ff',   # add sp, sp, #0x80
          'd65f03c0',   # ret
          'aa0003f6'],  # mov x22, x0
         'render-target state sync: a target whose handle was freed returns instead of dereferencing the null slot'),
        # the second render target of the same call may be the same freed handle (the log shows one object bound as both
        # colour 0 and 1): x19 has no check either and is stored into at the end of the function (main+0xacda94, +0xacdaac)
        (0xacd904, 'f30300aa',
         ['b5000100',   # cbnz x0, +0x20
          'a94657f6', 'a9455ff8', 'a9474ff4', 'a9436ffc', 'a9427bfd', '910203ff', 'd65f03c0',
          'aa0003f3'],  # mov x19, x0
         'render-target state sync: the second target of the call, same guard (its stores at +0xa4/+0xac would fault)'),
        # Leaving the tutorial (on the device: after the opening movie, quitting the tutorial) destroys an "AGC Allocator",
        # the game's own graphics memory allocator, with handle 0 -- its arena lookup answers 0 (main+0x5aabec tail-calls the
        # same slot+0x20 with the same null handle). The release path then zeroes a chunk descriptor at arena + the allocator's
        # span ([object+0x1b8], 0x200000) and splices it into the free list at [object+0x170]:
        #
        #   005aab88  ldr  x8, [x8, #0x20]   ; slot+0x20(iface, x21=0) -> 0
        #   005aab8c  blr  x8
        #   005aab90  ldr  x8, [x19, #0x1b8] ; 0x200000, the allocator's span
        #   005aab98  add  x8, x0, x8        ; 0 + 0x200000
        #   005aab9c  stp  q0, q0, [x8, #-0x20]!   ; sig=11 addr=0x1fffe0
        #
        # With no arena there is nothing to release: skip the zeroing and the list splice, and carry on at 0x5aabc8, which is
        # where the original code joins after that block (an allocator with no arena is the normal state of one that was never
        # given a block, so this is also what hardware does when the handle is valid but freed).
        (0x5aab98, '0800088b',
         ['b5000040',    # cbnz x0, +0x8  (an arena came back: run the original instruction)
          'b:0x5aabc8',  # no arena: the release below would write to address 0x1fffe0
          '8b080008'],   # add x8, x0, x8   (original)
         'AGC allocator release: no arena for the handle (0) returns to the join point instead of writing at span-0x20'),
    ],
}

# How general each patch is (dm/tools/docs_patches.py "Binding", listed in docs/agents/game-patches.md)
BINDING = [
    {'what': 'Unity render-target state sync: return when a target handle resolves to an empty slot', 'now': 'build', 'goal': 'game',
     'purpose': 'crash (use after free inside the game)', 'why':
     'the game frees a UI strip render target while draws that name it are still submitted, and this function dereferences the '
     'lookup result without the csel check its neighbour uses; the freed handle comes back as 0 from Unity\'s handle table '
     '(main+0xab5df0), so the sync runs on null', 'checked':
     'three device runs, each sig=11 at main+0xacd958 addr=0xa4 with a different strip size (1024x32, 1024x200, 1792x80), '
     'right after the first save commit'},
    {'what': 'AGC allocator release: skip the free-list splice when the handle has no arena', 'now': 'build', 'goal': 'game',
     'purpose': 'crash (null arena inside the game)', 'why':
     'the destructor of an "AGC Allocator" asks its back end for the arena of handle 0 and unconditionally zeroes a chunk at '
     'arena + span - 0x20; the lookup answers 0, so the store lands at 0x1fffe0', 'checked':
     'one device run: sig=11 addr=0x1fffe0 pc=main+0x5aab9c lr=main+0x5aab90, x0=0 x21=0 x8=0x200000, while quitting the '
     'tutorial after the opening movie'},
]
