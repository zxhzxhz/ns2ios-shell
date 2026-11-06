# PATAPON 1+2 Replay 1.0.7 (v458752): the server-environment query, keyed by main's NSO build ID.
#
# The Unity player asks nn::oe::GetServerEnvironmentType once on the boot path (main+0x29bfa40, one call site; the answer is
# then switched on 0..3) and dies there on this host: the SDK's oe::GetServerEnvironmentType is a four-byte tail branch into
# nn::nsd::GetApplicationServerEnvironmentType (sdk+0x3c6f40 is `b #0x5f8ca0`, the nsd PLT slot), whose IPC client connects
# nsd:u / nsd:a through sm and aborts with 0xE8D when the host refuses the connect -- nn::diag abort, Result 0xe8d, call site
# sdk+0x3aefa8, then FATAL. Nothing of the game's own runs before it: no [game] line, no draw.
#
# A retail console answers "Nintendo" (lp1 = the retail server environment), so the call returns 1 in place of the call. What the
# game does with the answer is behind networking, which this host cuts anyway (nn::nsd::Resolve and ResolveEx are HLE'd to a
# failure), so the value only has to be one the switch accepts.
#
# The host-side alternative -- an HLE for nn::oe::GetServerEnvironmentType, or DM_SF_SERVE=nsd:u,nsd:a -- needs a new shell; this
# patch is what the packer can do today. Drop it once a shell answers the symbol itself.
CUTS = {
    '37182df10df0f74166a88c8ccfa8ab89': [
        (0x29BFA40, 'b03cdf97', '20008052',
         'oe::GetServerEnvironmentType: return Nintendo/lp1 (w0 = 1) instead of calling nn::nsd, whose IPC client aborts 0xE8D '
         'when the host has no nsd service'),
    ],
}

# Whether a general rule could replace these patches (dm/tools/docs_patches.py lists it in docs/agents/game-patches.md)
GENERALIZE = ("Yes, in the host: nn::oe::GetServerEnvironmentType belongs in hle_oe.c next to GetRegionCode and GetPseudoDeviceId -- "
              "a single int answer, no game knowledge. Done on the shell branch patapon-nsd (commit 77fc02c) and waiting for a build.")
