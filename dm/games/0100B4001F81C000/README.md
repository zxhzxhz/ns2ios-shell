# Citizen Sleeper 2: Starward Vector / `0100B4001F81C000`

1.2.26 / `v786432`（base v0 + update），SDK 20，**Unity 6000.3.5f2 IL2CPP**，RomFS 148 文件 / 1,532 MB。
临时档案：上游 `seedds/nxnative` 与本仓库都没有这只 TID（两处都 404）。2026-11-01 首打成功，
IPA 1,944 MB / 17,455 个 metallib（库 `b-8878ca0a4c67`）。

## 引擎与文件

```
RomFS/Data/Managed/Metadata/global-metadata.dat   13.5 MB   IL2CPP
RomFS/Data/*.assets + *.assets.resS + level0..30   Unity 序列化文件，全部 stripped（不写类型树）
RomFS/Data/StreamingAssets/Master.bank            206 MB     FMOD
```

**没有任何 UnityFS bundle**（`Data/*.bundle` 一个都没有），所以 stripped 的 `.assets` 无处借类型树 ——
与一代 Citizen Sleeper（§38）完全同型，只是 Unity 版本从 2021.3.33f1 跳到了 6000.3.5f2。

Unity 版本来自 `Data/globalgamemanagers` 与 `sharedassets0.assets` 头里的长度前缀字符串：

```python
d = open('RomFS/Data/sharedassets0.assets','rb').read(0x40)
# ...\x36\x30\x30\x30\x2e\x33\x2e\x35\x66\x32\x00   = "6000.3.5f2"
```

`global-metadata.dat` 的 metadata version = 39。

## 着色器：补两个类型树才拆得出来（17,455）

不改 `unityfs.py` 时 `shader_split.py` 直接死在

```
[RED] Data/Resources/unity default resources: Unity serialized file without type trees, and no bundle has a
      Shader type tree of the same hash to borrow
```

普查（`tools_local/probe_trees_cs2.py`）给出两个缺失的 hash：

| 类 | type hash | 对象数 | 文件数 |
|---|---|---|---|
| 48 Shader | `57f0dd2d4ef24437b4655529a673a936` | 168 | 7 |
| 72 ComputeShader | `43a0948a3f403068c0b31bff90ba0c9a` | 21 | 2 |

两个布局都从 AssetRipper 的 `StructsDump/release/6000.3.5f2.dump` 取（`tools_local/dump2layout.py`），
**验证到 exact end 才登记**（`tools_local/verify_layout.py`：168/168、21/21，0 wrong-end、0 error）：

- `SHADER_6000_3` = `SHADER_6000_0` + 根上多一个 `SInt64 m_AssetLocalIdentifierInFile`（在 `m_AssetGUID` 之后），
  pass 仍然没有 `m_EditorDataHash` / `m_Platforms`；
- `COMPUTE_6000_3` = `COMPUTE_2022_3` + `ComputeShaderResource` 多一个 `int resType`，且 `threadGroupSize` 换成
  `staticvector`。**2022.3 的布局只能读对 6/21**，别拿邻近版本顶（§38 的老教训）。

拆出结果：**17,455**（pixel 8,670 / vertex 8,666 / compute 116 / geometry 3），`sources data 17444, main 11`；
3 个单 stage vs 用 pixel cover `aaedb27e9c515a6d` 配对；116 行 compute kernel 答案表。

## 内存：按 Unity 规矩 7 打（7 GB alias），未在设备上校准

```tsv
mem_reserve  0x210000000     # 8.25 GB
mem_alias    0x1C0000000     # 7.00 GB
mem_stack    0x10000000
app_pool     0xCD500000
sys_resource 0x1000000       # NPDM 声明 16 MB
```

`profile_guess.py` 猜的是 4 GB / 4.375 GB —— 对 Unity 的 TLSF 堆一律不够（§40 深空梦里人、§43 Sixtar Gate 都栽在这里）。
本作还没上设备，所以没有 `[mem] alias region mapped up to +X GB` 的高水位可对照；首测时按那条日志决定要不要再放宽，
不必重打包（`Documents/env.txt` 逐键覆盖）。

## 打包

```powershell
# NSZ 先解成 NSP（packer 只认 NSP/XCI），解出的 NSP 与更新包放同一个文件夹
nsz -D --keys I:\APP\ns2ios-shell\keys\prod.keys -o I:\APP\ns2ios-shell\workingdir\cs2_nsp "<...>[v0][APP].nsz"

cd I:\APP\ns2ios-shell\ns2ios-shell
python -u scripts\nxn_pack.py ..\dl-badc9f2\shell-20261101-8907429-badc9f2.zip ..\workingdir\cs2_nsp `
    -k ..\keys\prod.keys --tools ..\tools89074294 --work-dir ..\workingdir `
    -o ..\workingdir\CitizenSleeper2.ipa --name "Citizen Sleeper 2" `
    --bundle-id org.nxnative.0100b4001f81c000 --keep-work
```

耗时：提取 36 s → 重写 406/13/26 s → 拆分 8.6 s → **翻译 1,227 s（17,455 库）** → 装配+打包 ~7 min，合计 **35 min**。
中间产物 `0100B4001F81C000_pack` 5.5 GB。

**文件名与内容不符**：NSP 名写 `v1.0.0[..][v0]`，CNMT 的 version 是 786432、NACP 的显示版本是 **1.2.26** ——
packer 取的是 CNMT，profile 的 `build` 行按 `v786432 / 1.2.26` 登记，`build IDs match the profile for v786432` 可证。

## 打包后核对（PITFALLS §12，`tools_local/check_ipa.py`）

| 项 | 值 |
|---|---|
| Info.plist | `org.nxnative.0100b4001f81c000` / `Citizen Sleeper 2` / 1.2.26 |
| `dm/env.txt` | reserve 0x210000000、alias 0x1C0000000（与 profile 一致） |
| `msl/b-8878ca0a4c67/inputs.tsv` | `inputs e71921235d65`，**无 `\r`** |
| `c1_full.tsv` / `cb_extent.tsv` 首行 | 与 stamp 逐字节一致（§5 的 CRLF 坑没有复发；日志 `text files written with LF endings: 17492`） |
| metallib | 17,455（= 表里 17,455，两数相等） |
| gates | `cntpct obs spin svc` ⊂ 壳派发集合 `cntpct cntvct obs spin svc` |
| 图标 | `AppIcon60x60@3x.png` 180×180 / 58,901 B（非纯色） |

## 遗留

- **`pso_manifest.tsv` 为空**：设备还没跑过，首开会有管线编译长帧。按 §6 真机跑一遍，把沙盒里的 `pso_user.tsv`
  原样放进本目录即开机预热。
- **未上设备验证**：一代 Citizen Sleeper 的两个崩溃点在本作是否复现仍是未知 ——
  §37 的 `nvnTextureGetTarget(NULL)`（来宾把查不到的纹理句柄直接喂给 host）与 §40 的 alias 地址空间耗尽。
  壳 `shell-20261101-8907429-badc9f2` 是否含 §37 的守卫，同样没有对过；崩溃时按那两节的判据读寄存器
  （`x0=0 → addr=0x4` / `addr=0x…ffe0`、`*x19` 指向 `ALLOC_GFX_THREAD`）即可分流。
- `shader_map.tsv` 里有 116 行 compute（Unity 的 post-processing 那批 `MultiScaleVO* / ExposureHistogram /
  Waveform / Vectorscope / GaussianDownsample`），一代没有这么多 —— 若出现「角色不动 / 变形错」这类 GPU 蒙皮症状，
  先查 compute 表是否被 `graphics_route` 认下（§9）。
