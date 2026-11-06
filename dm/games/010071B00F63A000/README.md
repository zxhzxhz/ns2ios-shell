# Eastward (`010071B00F63A000`)

Update 1.2.1 (v589824) over the base game, **SDK 16**. Provisional profile, written on Windows from `dm/games/profile_guess.py` — never booted, neither here nor upstream.

## Status: not packable without a run-time capture

| Fact | Evidence |
|---|---|
| Modules `main`, `subsdk1` (GLSLC), `sdk` | `profile_guess.py`; `subsdk0` is NintendoSDK_OpenGL and main takes nothing from it the host does not supply |
| The game compiles its GLSL **at run time** | `main` imports `glslcInitialize`, `glslcGetDefaultOptions`, `glslcCompile`, `glslcSetAllocator`, `glslcFinalize` |
| No file holds its shaders | `shader_split.py` over the whole 1.4 GB RomFS: `shaders: 0 ()` |
| So the whole shader library is missing | the package would boot, play music and draw nothing |

The packer's shaderless build is the capture vehicle. Upstream collects the GLSLC outputs by booting the game in the **Mac host** with
`DM_GLSLC_CAPTURE=<version dir>/glslc_capture` (`dm/host/hle_glslc.c`), then `shader_split.py` reads that folder through
`shader_groups ... /glslc_capture/=runtime` — the route `010055D009F78000` uses for its 9 built-in shaders.

`scripts/nxn_pack.py`'s own capture stages (`capture_gl`, `build_mac_host`) refuse to run off macOS, so on Windows the capture has to come
from a device run instead:

1. pack with `--no-shaders` (this profile) — the app boots and dispatches its GLSL to the host's `glslcCompile`;
2. run it on the phone with `DM_GLSLC_CAPTURE=<writable dir>` in `dm/env.txt`;
3. copy the `*.glslc` files back, put them under `<work>/extract/v589824/glslc_capture/`, rerun the split and translate with
   `dmsh_xlate` (a GLSLC output is the same control + code format the NVN route uses);
4. pack again with the resulting `shader_map.tsv` / `shader_facts.tsv` / `shader_pairs.tsv` / `pso_pairs.tsv`.

## Memory

| Key | Value | Why |
|---|---|---|
| `mem_reserve` | `0x100000000` | main sets a heap of at most pool − 64 MB |
| `mem_alias` / `mem_stack` | `0x10000000` | guess defaults |
| `app_pool` | `0xCD500000` | guess default |
| `sys_resource` | `0x0` | the NPDM declares 0 MB (virtual address memory disabled) — same as the other NintendoWare titles here |

None of it is verified: a first run may abort in `nninitStartup` (module list) or `SetHeapSize` (heap).

## Files

| Item | Size |
|---|---|
| RomFS | 59 files, 1402 MB (Wwise `.bank` audio 1.1 GB, `gfx.g` / `asset.g` / `scene_main.g` / `ttf.g` archives) |
| main | build `42dce9ac5414038008cd642607928597`, bss 3.2 MB, 589 imports |
| sdk | build `3053b22935e32ddf15ef81997603e5c2` (SDK 16) |
| subsdk1 | GLSLC, build `e0d8adcc446cf14d6af1a51193f72e30` |

## Packing

```powershell
py scripts\nxn_pack.py <shell.zip> <nsp folder> -k prod.keys --tools <tools> --work-dir <ssd> \
   -o <out.ipa> --name 风来之国 --bundle-id org.nxnative.010071b00f63a000 --no-shaders
```

(`.nsz` files must be decompressed to `.nsp` first: `nsz -D --keys prod.keys -o <dir> <file>.nsz`.)

