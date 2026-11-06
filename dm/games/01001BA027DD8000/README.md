# ほの暮しの庭（静谧田园）/ `01001BA027DD8000`

1.2.0 / `v393216`（base v0 + update），SDK 20，RomFS 3,183 文件 / 4.17 GB。临时档案（上游与本仓库都没有）。
2026-11-01 三版：v1 只有 RomFS 的 198 个着色器 → **装上去有声有操作、画面全黑**；v2 补上 NRO 里的 918 个 →
1,116 个 metallib（库 `b-8878ca0a4c67`），**实测 60 fps / 无缺失 shader**；v3 = v2 + 回填的 `pso_manifest.tsv`，
IPA 3,978 MiB。

## 引擎与文件

NMPL 自研引擎（模块 `main + sdk`，Lua 脚本 936 个 `data/script/*.lub`），RomFS 几乎全是**自定义 `FAFULLFS` 归档**：

```
0x00  "FAFULLFS"        u32 count at +0x08
+0x10 data length        +0x18 data offset     （+0x10 + 0x18 == 文件大小，可据此判读）
data/shader_1_00.dat   0x9C0 起是记录区，"NMPL_NVN" 记录里直接是 NVN control section + code area
```

`data/` 顶层：`map / fairy / texture / misc / bgm / se / msg / shader` 各一个 `_NN.dat`，其余是 `database/*.dat`、
`navi/*.navi`、`script/*.lub`。

## 着色器：RomFS 里 198 个，真正在用的 1116 个（918 个在 NRO 里）

| 判据 | 值 |
|---|---|
| RomFS 里 `BNSH\0\0\0\0` | **0 个**（`shader_split.py` 原样跑出 `shaders: 0`） |
| `main` 里 GLSLC 输出 / GLSL 源 / SPIR-V | 0 / 0 / 0 |
| RomFS 的 `FAFULLFS` | `data/shader_1_00.dat` 140 个 stage（70 vs + 70 ps）+ `data/fairy_1_00.dat` 58 vs = **198** |
| **`NmplDLL.nro`** | control 1149 / code 934 GFX + 215 CS = **1149 条**，key 去重后 **918** |
| 每条的布局 | control 自身长度在 `+0x20`（0x880），code area 紧接其后（16 字节对齐），code 长度在 control `+0x704`（NVN 通用约定） |
| 合计 | **1,116**（pixel 734 / vertex 165 / compute 215 / geometry 2），`sources nro 918, data 198` |

`dm/gfx/tools/shader_split.py` 为此加了两组（`FABLFS_MAGIC` / `NRO_MAGIC` / `nvn_tight_pairs()` 及两个薄封装 /
预过滤器放行 / `'#FABLFS@'`、`'#NRO@'` 进 `SINGLE_STAGE`）：165 个 vs 是单 stage 程序，靠 `separable_pairs` 与 pixel
cover（本次 cover 只有 1 条 `3b64edce246f26e2`）配对生成 `shader_pairs.tsv`，否则 `vs_pad` 拿不到顶点输出并集。

**运行期没有 GLSLC 现编**：`NmplDLL.nro` 里的 `glslcCompile*` 全是 weak 未定义（日志
`nro0: undefined weak glslcCompilePreSpecialized bound to 0`），所以缺的 shader 只能从文件里挖 —— 不要去抓
`DM_GLSLC_CAPTURE`。

v1 黑屏的设备证据（`[RED] shader … is not in the shader map` 共 11 个 key，v2 的 1,116 条表 11/11 全覆盖）：

```
[dm] [nvn-mtl] shader route B (translated Switch originals): shader map 198 entries
[dm] [nvn-mtl] [RED] shader e57003750849ab06 is not in the shader map (DM_NVN_SHDUMP=…)
[dm] [nvn-mtl] [RED] program has no vertex shader (or it is not mapped)
[dm] [nvn] on-screen up to frame 300: 289 frames, dropped 1 … brightness 0.44
```

## NRO（`nn::ro::LoadModule`）

RomFS 有 `/.nrr/village.nrr` 与两个裸 NRO，packer 的 `step_nros()` 正常收下（`dm/nro.tsv` 两条）：

| NRO | 大小 | 来源 | 着色器 |
|---|---|---|---|
| `nro0` | 10,805,248 | `NmplDLL.nro`（引擎 DLL） | **1,149 条 control/code 对 → 918 个唯一 key** |
| `nro1` | 151,552 | `lz4.nro` | 无 |

NRO 头 `NRO0` 在 **+0x10**，不在文件头 —— `shader_split.py` 的判据是 `d[:4] == b'NRO0' or d[0x10:0x14] == b'NRO0'`。

## 内存：仍是 `profile_guess` 的猜测，未校准

```tsv
mem_reserve  0x100000000     # 4 GB
mem_alias    0x10000000      # 256 MB
mem_stack    0x10000000
app_pool     0xCD500000
sys_resource 0x0             # NPDM 声明 0，IsVirtualAddressMemoryEnabled 为 false
```

非 Unity（自研 NMPL），所以没有按「Unity 一律 7 GB alias」那条走。设备实测
`[mem] alias region mapped 2.00 GB (application pool 3.21 GB)`、`resident 3069 MB`，没有 §40 那种 alias 撞墙崩溃。
真要放宽时不必重打包：用 AFC 写 `Documents/env.txt` 覆盖即可验证。

## 已知问题（未解决）

**title 画面房子右侧有一块半透明洋红/粉色斜带 + 青色线框**，位置固定、**形状与图案每次启动都不同**；`Now Loading` 与
`TEAM 夜廻` logo 干净，游戏内也只在部分物件上出现；音频、操作、存档、60 fps 全正常。

查到的因果链（完整流程与排除项见 `PITFALLS.md` §44.6）：title 每帧只有 3 个 draw、2 组 program；顶点 / UV / 顶点色
全部正确；数据流是 `ASTC 6x5(ser 475) → RGB10A2 RT(ser 258/259) → 屏幕`；**用 `DM_NVN_TEXDUMP=900` dump 出的 RT 里
就已经有色带**，即 pass 1 采样那张 ASTC 时带进来的。那张纹理 `has_layout=1, block_h=4`，storage 1,310,720 字节里
**只写了 690,063 字节**，其余是池里的旧内容。

已试无效：`tex_flush_upload` / `tex_dirty_upload`、`DM_NVN_VBUF_CACHE=0`、`DM_NVN_ZBLOCK`（0 个全零块）、
`DM_NVN_HILITE` 逐个涂色（30 个 ps 里能测的都测了，色带始终不变）、`DM_NVN_PKG_REUPLOAD=1`（每次绑定强制重传，
色带原样）—— 后者说明交给 GPU 的内容就是游戏自己写的那份。

剩下的方向：ASTC **块布局 / storage 大小**。`level_walk` 对 1920x1080 给 `0x140000`（与手算一致），对 1024x1024 给
`0xC0000` 而按 GOB 规则手算只有 `0xAC000`（差 0x14000）—— 若 `nvnTextureBuilderGetStorageSize` 的返回值与真机不同，
游戏按它的返回值排布的偏移会与 host 认为的错开，整条纹理链从某一张起整体移位。这只游戏的包本身完全可玩，只是标题那一块不好看。

## 遗留

- `pso_manifest.tsv` **已回填 92 行**（设备 v2 跑 6.6 分钟后 `pso_user.tsv` 的 49 S + 43 R），包内置。
- `c1_full.tsv` 只有表头（`not proven bounded: 0 shaders`），`cb_extent.tsv` 与 stamp 一致（LF）。
- **改了表必须清 `<work>/shader/cache/b-<V>` 和 `<work>/build/ios/dmsh_b/<V>`**，否则 `dmsh_build` 报
  "shader libraries already there" 并留用旧库（v1→v2 就栽在这里，packer 会拦下来报 198 vs 1116）。
- 密钥：本作 key generation **0x15**，旧 `prod.keys`（到 0x13/0x14）解不动，`nx_extract` 报
  `MissingKeyException: key_area_key_application_15`。打包用的是 `I:\APP\ns2ios-shell\keys\prod.keys`（22 代齐全）。
- **v2 实测（6.6 分钟 / 23,700 帧）**：`shader map 1116 entries`、`is not in the shader map` 归零、60 fps 稳
  （frame p50 16.67 / p99 16.67、dropped 0）、GPU 5.04 ms、footprint 2,168 MiB、heap 3.11 / 3.25 GB。
  RED 只剩三条噪声：`nvnQueueResetMemoryUsageCounts` 未实现（94 次，void 语义，无害）、shader library
  "built for game … not 0000000000000000"、pipeline prewarm 缺表（已解决）。
- 唯一的日志噪声来源：壳每帧打一行 `[dm] [nvn] depth mode near=0 (as D3D / Metal)` —— 8.7 MB / 182k 行日志里
  180,307 行是它（99%）。属壳源码，要降频得动 CI 出的壳，不影响运行。
- **诊断开关一律默认关**：`DM_DRAWLOG` / `DM_NVN_PKG_REUPLOAD` 都在壳里但默认关；设备上的 `Documents/env.txt`
  会整份覆盖包内的 `dm/env.txt`，诊断完记得删掉它。
