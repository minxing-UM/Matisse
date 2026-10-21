# Matisse

[English](#english) · [中文](#chinese)

<a id="english"></a>

## English

A local AI companion architecture with selective long-term memory, emotional state that persists across turns, emotional resonance, and queued self-initiated messages. Both the interface and generated replies can switch between English and Chinese.

This release contains the architecture and source code. It excludes model weights and the author's private personality, character history, chats, memories, and avatar. Each user creates their own character.

### Windows quick start

1. Extract the project into a writable directory. Initial downloads require an internet connection and enough disk space for the models and Python environment.
2. Copy `examples/Modelfile.example` to `Modelfile` in the project root and edit `FROM` to use an Ollama model tag or a local GGUF path. See the model suggestions below. This step is optional: the launcher creates a default file if it is missing.
3. Double-click **`Start.cmd`**.
4. When the browser opens, enter and save your own character settings in the **Customize your character** dialog. Press Ctrl+C in the launcher window to stop the backend, then run `Start.cmd` again to apply them. You can reopen the editor under **Settings → Edit character personality**.

The launcher performs these steps in order:

- Check for Python 3.11+ and Ollama. If missing, install Python 3.12 or Ollama through Windows `winget`.
- Create `.venv` and install `requirements.txt`. Skip installation if the requirements have not changed and the dependencies are available.
- Create missing configuration files, an empty personality file, and an empty character history. Preserve existing configuration.
- Check the Ollama service and start a local `ollama serve` if needed.
- Run `ollama create <model> -f Modelfile` on first setup, when `Modelfile` changes, or when the target model is missing. An uncached base model may need downloading; users must supply their own local GGUF files.
- Run `ollama pull bge-m3` if semantic retrieval is enabled and the embedding model is missing. The default tag is `bge-m3:latest`.
- Open the local interface at `http://127.0.0.1:8787`. Press Ctrl+C in the launcher window to stop the service.

Installers may ask you to approve permissions. The script does not install GPU drivers; install an appropriate driver for your GPU beforehand. If `winget` is unavailable or installation fails, manually install [Python](https://www.python.org/downloads/windows/) and [Ollama](https://ollama.com/download/windows), then run `Start.cmd` again. See the [official Ollama Windows documentation](https://docs.ollama.com/windows) for installation paths and hardware requirements.

Command-line options, run from the project root:

```powershell
.\Start.cmd -Check           # Check Python, Ollama, and the service without installing or changing files
.\Start.cmd -PrepareOnly     # Prepare dependencies and models without opening the interface
.\Start.cmd -Rebuild         # Force a model rebuild even if Modelfile has not changed
.\Start.cmd -SkipEmbeddings  # Skip the embedding model download for this run; preserve the retrieval setting
```

Retry after a failed download; failed model creation is not marked as complete. Use `-Rebuild` if you replace a GGUF file without changing its path or update a base model under the same tag. `OLLAMA_HOST` can point to an existing service. If a configured remote service is unreachable, the launcher reports an error rather than switching to a local service.

#### Modelfile and character settings

`Modelfile` selects the base model, quantized file, and model defaults. Changes require `ollama create`, which the launcher handles. The [Ollama Modelfile reference](https://docs.ollama.com/modelfile) covers `FROM`, GGUF paths, and model creation.

The `model` field in `config/settings.json` names the model to create; its default is `matisse-local`. Use a name different from the base model in `FROM`. Context length, output limit, and temperature sent by the application override the Modelfile defaults; adjust them in the interface settings.

**`config/personality.md` holds your own character settings.** Leave the Modelfile's `SYSTEM` section empty to avoid conflicting personality instructions. Do not copy private chats or personality settings into the public example files.

### Customize your character

- A fresh installation starts with an empty `personality.md`. With `personality_required=true`, you must customize it before personal chats or quick interactions are available.
- View and edit the raw Markdown under **Settings → Edit character personality**, or use your own text editor. See `examples/personality.example.md` for an outline.
- Saving writes only to the local file. The running backend keeps the personality snapshot loaded at startup. External edits also require a backend restart. The editor indicates pending changes; refreshing the page does not apply them. Restart after the first save to begin personal chats.
- To restart, press Ctrl+C in the launcher window, then run `Start.cmd` again. The personality is included once in the existing system prompt structure, not appended as a chat message. Caching the file at startup does not reduce the input tokens occupied by its text. Personality edits require no training or model rebuild; Modelfile edits require a rebuild.
- If another window or external editor changes the file, saving an outdated version is rejected while your draft remains in the editor. Copy any edits you want to keep, then use **Reload file** to merge them.
- Personality text is saved as written and is not translated when the interface language changes. Existing chats, memories, personality tags, and `config/character_canon.json` still affect replies; changing the personality does not clear them.
- Self-initiated messages are disabled on fresh installations. Enable them in settings and customize the long-term direction, waking hours, random intervals, and quiet hours.

Existing personal installations are not reset to a blank character. The public default character history contains no fixed past events and does not load the author's private personality.

### Models and GPU guidance

#### Author's test environment

The author uses the following device and models for everyday development and testing. This records the actual configuration; no standardized latency or throughput benchmark has been conducted.

| Item | Configuration |
| --- | --- |
| Computer | Alienware 16 A51 |
| GPU | NVIDIA GeForce RTX 5090 Laptop GPU, 24 GB VRAM |
| Inference backend | Ollama, running locally |
| Chat model | A local `uncensored` GGUF variant of Gemma 4 26B-A4B Instruct |
| Parameter scale / quantization | 26B-class MoE; approximately 25.2B total parameters in local metadata; Q4_K_M |
| Memory retrieval model | `bge-m3:latest` |
| Context / output limit | 12288 / 2048 tokens |
| Temperature | `0.7` |
| Thinking | Off for everyday chat; enable as needed, with potentially much longer waits |

This is the **24 GB laptop version** of the 5090. Choose models based on your device's actual VRAM. The author's local weights are not distributed with the project. The Ollama library models below are available separately and may behave differently from that local variant.

`B` means billion parameters: 8B is approximately eight billion. Gemma 4 26B-A4B uses a mixture-of-experts (MoE) architecture. Its official model card lists approximately 25.2B total parameters and 3.8B active parameters per token, rounded to 4B. Memory planning must still account for the full weights; do not size it like a regular 4B model. See the [Google model card](https://ai.google.dev/gemma/docs/core/model_card_4) and [memory requirements](https://ai.google.dev/gemma/docs/core).

#### Choose a model by VRAM

These are **conservative starting points based on VRAM headroom, not project benchmarks or compatibility certifications**. GPU names illustrate VRAM capacities; laptop variants, memory configurations, and driver support can differ. Choose a quantized model that fits your hardware, then evaluate structured replies, memory extraction, and multi-turn conversations in this project.

| VRAM and example GPUs | Suggested `FROM` | Parameters / quantization | Approx. weight download | Starting context / output | Thinking |
| --- | --- | --- | --- | --- | --- |
| 6 GB, e.g. RTX 2060 6GB | `qwen3:4b-q4_K_M` | 4B / Q4_K_M | 2.6 GB | 4096 / 768 | Off |
| 8 GB, e.g. RTX 3060 Ti, 4060 8GB | `qwen3:4b-q4_K_M` | 4B / Q4_K_M | 2.6 GB | 8192 / 1024 | Off |
| 12 GB, e.g. RTX 3060 12GB, 4070 | `qwen3:8b-q4_K_M` | 8B / Q4_K_M | 5.2 GB | 8192 / 1024 | Off |
| 16 GB, e.g. RTX 4060 Ti 16GB, 4070 Ti SUPER | `qwen3:14b-q4_K_M` | 14B / Q4_K_M | 9.3 GB | 8192 / 1536 | Start with off |
| 24 GB, e.g. RTX 3090, 4090 | `qwen3:14b-q4_K_M` | 14B / Q4_K_M | 9.3 GB | 12288 / 2048 | Start with off |
| 24 GB, Gemma 4 family candidate; the author uses a local variant on a 5090 Laptop 24GB | `gemma4:26b-a4b-it-q4_K_M` | 26B-class MoE, about 4B active / Q4_K_M | 18 GB | 8192 / 1024; try 12288 / 2048 after validation | Start with off |
| 32 GB, e.g. RTX 5090 | `qwen3:32b-q4_K_M` | 32B / Q4_K_M | 20 GB | 8192 / 2048 | Start with off |

Qwen3 tags, quantization, and download sizes come from the [Ollama Qwen3 tag list](https://ollama.com/library/qwen3/tags). These are verifiable starting options, not claims about the newest or best models. Other instruction models supporting Ollama structured outputs can also be evaluated.

See the [Ollama model page](https://ollama.com/library/gemma4:26b-a4b-it-q4_K_M) for the Gemma 4 candidate's tag, quantization, and approximately 18 GB download. This library model has not been independently tested in this project. With 24 GB VRAM, start with a shorter context to leave room for embeddings and runtime overhead.

Other comparison options include `gemma3:4b-it-q4_K_M` (4B, about 3.4 GB), `gemma3:12b-it-q4_K_M` (12B, about 8.2 GB), and `gemma3:27b-it-q4_K_M` (27B, about 17 GB). Start with a shorter context and thinking disabled; this family does not support the reasoning switch used by the project. Sizes are listed in the [Ollama Gemma 3 tag list](https://ollama.com/library/gemma3/tags). Personality adherence, affect attribution, and JSON reliability need evaluation for each model; switching models does not guarantee the same expression.

**Download size is not total VRAM usage.** Allow room for the KV cache, runtime buffers, desktop display, and embedding model. [`bge-m3`](https://ollama.com/library/bge-m3) is approximately 1.2 GB and handles cross-language memory retrieval, not chat. Ollama may load or unload models or offload part of them to system memory, so weight size alone does not establish performance. If VRAM is tight, shorten the context, disable thinking, then try a smaller model. Disabling semantic retrieval in settings switches to keyword retrieval.

Start with temperature `0.7` and an output limit of `1024`. Each turn also generates internal structured fields; an overly small output budget may cause failures. A small model being able to run does not establish reliable emotion and memory processing. Base models retain their publishers' terms; the code license does not cover model weights.

### Manual startup / macOS and Linux

The Windows launcher is the current automatic installation entry point. On other systems, install Python 3.11+ and [Ollama](https://ollama.com/download), start Ollama, then run from the project root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp examples/Modelfile.example Modelfile  # Edit as needed; do not overwrite an existing file
.venv/bin/python scripts/bootstrap.py
```

On Windows with an existing environment:

```powershell
.\.venv\Scripts\python.exe scripts/bootstrap.py
```

After initial setup, you can start the interface directly with `python app/backend/web_server.py`. This skips automatic model rebuilding and dependency downloads. The CLI entry point is `python app/backend/main.py`.

### Architecture and demo

The main path for a conversation turn:

```text
User message → Generation queue → Relevant memories + Current emotions + Custom personality
             → Structured model output → Reply quality / Language checks
             → Emotional resonance and delta merging → Persistent state → Next-turn context
```

Memories have importance scores, reinforcement, expiration, and semantic or keyword retrieval. Currently, "forgetting" marks a memory inactive and stops retrieving it while preserving the original record. It does not permanently delete private data.

Self-initiated thoughts share the generation queue. A thought already being generated finishes before a queued user message is processed. The model can skip when it has nothing new to share, and text checks reject obvious repetition. See [self-initiated messages](docs/spontaneous-thoughts.md) and [emotions and resonance](docs/emotions.md); these detailed documents are currently in Chinese. The long-term direction is prompt context, without autonomous training or goal achievement evaluation.

The work demo at `/demo` requires a T0–T3 relationship tier for each new chat. It uses separate temporary emotional state and does not load personal prompts, chats, or memories. Generic relationship instructions replace the user's private character settings. The default T0 demo password is `0423`; set `MATISSE_DEMO_T0_PASSWORD` to change it.

This is a local, single-user application bound to `127.0.0.1`. The demo password is not a site-wide login system. Authentication and multi-user isolation for public hosting are not implemented.

### Build a public source archive

Do not upload your personal working directory directly. Run from the project root:

```powershell
.\.venv\Scripts\python.exe scripts/prepare_release.py
```

The script builds `dist/matisse-source-<timestamp>.zip` using an explicit public file allowlist. It includes code, tests, generic examples, and documentation without reading or copying real `config/`, `repository/`, `Modelfile`, model weights, or avatars. Add new public files to the allowlist explicitly. `.gitignore` also excludes local private files, but does not remove content already committed to Git history.

Review the archive before publishing; the generated ZIP is a release candidate.

### License and models

The project's original code and accompanying documentation are licensed under the [MIT License](LICENSE). Use, modification, distribution, commercial use, and closed-source modifications are permitted. Distribution of the software or substantial portions must retain the copyright and permission notices. The software is provided as is, without warranty; see `LICENSE` for the full terms.

Sharing your improvements publicly is welcome, but optional.

This repository excludes language model weights, embedding model weights, and the author's private character settings, chats, memories, and other personal runtime data. Private material not distributed with the project is outside the scope of this license grant.

Third-party components retain their own licenses. Users must obtain models separately and follow the relevant model and service terms. This project's MIT License grants no additional rights to third-party models or components.

### Verification

```powershell
python -m unittest discover -s tests -p "test_*.py"
node tests/test_frontend_thoughts.cjs
node tests/test_frontend_sadness.cjs
node tests/test_frontend_memories.cjs
node tests/test_frontend_demo.cjs
node tests/test_frontend_language.cjs
node tests/test_frontend_personality.cjs
```

Node.js is needed only for frontend tests, not normal use. Automated tests use isolated directories and mocked model responses; they do not read personal chats or call a real language model. Content quality, hardware performance, and installation under different network conditions require separate testing.

[Back to language selection](#matisse) · [中文](#chinese)

---

<a id="chinese"></a>

## 中文

一个本地运行的 AI 伴侣架构：选择性长期记忆、跨轮延续的情绪状态、情绪共鸣，以及可排队的主动发言。提供中文 / English 界面和回复语言切换。

这是架构与代码的公开版本。模型权重、作者的人格设定、角色档案、聊天、记忆和头像不包含在发行包中。每位使用者需要创建自己的角色。

### Windows 快速开始

1. 解压项目到可写目录。首次下载需要联网，并预留模型和 Python 环境所需的磁盘空间。
2. 把 `examples/Modelfile.example` 复制为根目录的 `Modelfile`，修改 `FROM`：可以写 Ollama 模型标签，也可以写本地 GGUF 的路径。模型建议见下表。不复制也可以：启动器会创建默认文件。
3. 双击 **`Start.cmd`**。
4. 浏览器打开后，在自动弹出的「定制角色性格」窗口写下你自己的设定并保存。在启动窗口按 Ctrl+C 关闭后端，再双击 `Start.cmd`，新设定才会生效。以后可从「设置 → 编辑角色设定」打开。

启动器按顺序完成：

- 检查 Python 3.11+、Ollama；缺少时通过 Windows 的 `winget` 安装 Python 3.12 或 Ollama。
- 创建 `.venv` 并安装 `requirements.txt`。依赖清单未变且依赖可用时跳过安装。
- 只在文件缺失时创建配置、空白人格和空白角色档案。已有配置不会被替换。
- 检查 Ollama 服务，必要时启动本地 `ollama serve`。
- 首次运行、`Modelfile` 改变或目标模型丢失时执行 `ollama create <model> -f Modelfile`。基础模型尚未缓存时可能需要下载；本地 GGUF 必须由使用者自己准备。
- 启用语义检索且尚未缓存时执行 `ollama pull bge-m3`（默认实际标签为 `bge-m3:latest`）。
- 启动本机网页 `http://127.0.0.1:8787`。关闭服务请在启动窗口按 Ctrl+C。

安装界面可能要求确认权限；脚本不安装 GPU 驱动。请预先安装适合自己显卡的驱动。Windows 的 `winget` 不可用或安装失败时，先手动安装 [Python](https://www.python.org/downloads/windows/) 和 [Ollama](https://ollama.com/download/windows)，再运行 `Start.cmd`。Ollama 的安装路径、硬件条件见[官方 Windows 文档](https://docs.ollama.com/windows)。

命令行选项（在项目根目录）：

```powershell
.\Start.cmd -Check           # 只检查 Python、Ollama 和服务，不安装、不建模、不修改配置
.\Start.cmd -PrepareOnly     # 完成安装、建模与嵌入模型准备，暂不启动网页
.\Start.cmd -Rebuild         # 强制重建，即使 Modelfile 文本没有变化
.\Start.cmd -SkipEmbeddings  # 本次不下载嵌入模型，不改变检索开关
```

下载失败时重试即可；失败的模型创建不会被标记为完成。修改 GGUF 内容但路径未变、或更新同名基础模型后，可用 `-Rebuild`。`OLLAMA_HOST` 可指定已有服务；远程地址不可达时启动器会报错，不会替换为本机服务。

#### Modelfile 与角色设定的区别

`Modelfile` 负责选基础模型、量化文件与模型默认参数；更改它以后需要 `ollama create`。启动器会处理这一步。[Ollama Modelfile 参考](https://docs.ollama.com/modelfile)说明了 `FROM`、GGUF 路径和创建命令。

`config/settings.json` 中的 `model` 是创建后的目标名称，默认 `matisse-local`。它应与 `FROM` 的基础模型名不同。应用发送的上下文、输出上限和温度参数优先于 Modelfile 中的默认值；在网页设置中调整这些参数。

**`config/personality.md` 负责使用者自己的角色设定。** 保持 Modelfile 的 `SYSTEM` 部分为空，可避免两个地方的人格说明冲突。不要把私人聊天或人格复制进公开的示例文件。

### 自定义角色

- 新安装的 `personality.md` 为空；`personality_required=true` 会要求先填写人格，再进行个人对话或轻互动。
- 在「设置 → 编辑角色设定」中直接查看、编辑 Markdown 原文；也可以用自己的文本编辑器修改文件。提纲见 `examples/personality.example.md`。
- 保存只写回本机文件，后端运行期间使用启动时的人格快照；外部编辑文件也需要重启后端才能生效。窗口会提示尚未生效的修改，刷新网页不会应用新设定。首次填写人格后也需要重启，才能开始个人对话。
- 重启方法：在启动窗口按 Ctrl+C 停止服务，再运行 `Start.cmd`。人格仍沿用原有系统提示词结构，只拼入一次，不追加成聊天消息；启动时缓存文件不会减少人格文本本身的输入 token。更改人格不需要训练或重建模型，修改 Modelfile 时才需要重建。
- 窗口打开后，如果文件被其他窗口或外部编辑器修改，旧版本保存会被拒绝，保留输入框中的草稿；复制需要保留的修改，再点「重新载入文件」合并。
- 人格内容按原文保存，不随界面语言切换而翻译。旧聊天、记忆、性格标签和 `config/character_canon.json` 仍会影响回答；改人格不会清空它们。
- 新安装默认关闭主动发言，避免在定制完成前自行运行。设置中可启用并修改长期方向、清醒时段、随机间隔和静默时段。

已有的个人安装不会被迁移为空白角色。公开默认角色档案没有固定经历，也不加载作者的私人人格。

### 模型与显卡参考

#### 作者测试环境

作者日常开发、测试使用以下设备与模型；这是实际使用配置，尚未进行统一的延迟或吞吐基准测试。

| 项目 | 配置 |
| --- | --- |
| 电脑 | Alienware 16 A51 |
| GPU | NVIDIA GeForce RTX 5090 Laptop GPU，24 GB 显存 |
| 推理后端 | Ollama，本地运行 |
| 对话模型 | Gemma 4 26B-A4B 指令模型的本地 `uncensored` GGUF 变体 |
| 参数量级 / 量化 | 26B 级 MoE；本地元数据约 25.2B 总参数；Q4_K_M |
| 记忆检索模型 | `bge-m3:latest` |
| 上下文 / 输出上限 | 12288 / 2048 tokens |
| 温度 | `0.7` |
| 深度思考 | 日常聊天关闭；按需开启，开启后等待时间可能明显增加 |

这里的 5090 是 **24 GB 的笔记本版本**，选模型时请以自己设备的实际显存为准。作者使用的本地模型权重不随项目发布；下方 Ollama 库模型供使用者自行获取，不保证与该本地变体有相同的表达和行为。

`B` 表示十亿参数，例如 8B 约为 80 亿参数。Gemma 4 26B-A4B 属于混合专家（MoE）模型：官方模型卡给出的总参数约 25.2B、每个 token 激活约 3.8B（约 4B）；显存规划仍需考虑整体权重，不能按一个普通 4B 模型估算。见 [Google 模型卡](https://ai.google.dev/gemma/docs/core/model_card_4)及[内存需求说明](https://ai.google.dev/gemma/docs/core)。

#### 按显存选择模型

下表是**按显存余量给出的保守起点，不是本项目实测性能榜或兼容认证**。显卡型号仅作显存举例；同名笔记本显卡、不同显存版本和驱动支持可能不同。优先选择适合自己显存的量化模型，再用本项目的结构化回复、记忆提取和多轮对话验证质量。

| 显存及显卡举例 | 可先尝试的 `FROM` | 参数量 / 量化 | 权重下载大小约 | 上下文 / 输出起点 | 深度思考 |
| --- | --- | --- | --- | --- | --- |
| 6 GB，例如 RTX 2060 6GB | `qwen3:4b-q4_K_M` | 4B / Q4_K_M | 2.6 GB | 4096 / 768 | 关闭 |
| 8 GB，例如 RTX 3060 Ti、4060 8GB | `qwen3:4b-q4_K_M` | 4B / Q4_K_M | 2.6 GB | 8192 / 1024 | 关闭 |
| 12 GB，例如 RTX 3060 12GB、4070 | `qwen3:8b-q4_K_M` | 8B / Q4_K_M | 5.2 GB | 8192 / 1024 | 关闭 |
| 16 GB，例如 RTX 4060 Ti 16GB、4070 Ti SUPER | `qwen3:14b-q4_K_M` | 14B / Q4_K_M | 9.3 GB | 8192 / 1536 | 先关闭 |
| 24 GB，例如 RTX 3090、4090 | `qwen3:14b-q4_K_M` | 14B / Q4_K_M | 9.3 GB | 12288 / 2048 | 先关闭 |
| 24 GB，Gemma 4 同系列候选；作者使用 5090 Laptop 24GB 的本地变体 | `gemma4:26b-a4b-it-q4_K_M` | 26B 级 MoE，约 4B 激活 / Q4_K_M | 18 GB | 8192 / 1024，验证后可尝试 12288 / 2048 | 先关闭 |
| 32 GB，例如 RTX 5090 | `qwen3:32b-q4_K_M` | 32B / Q4_K_M | 20 GB | 8192 / 2048 | 先关闭 |

标签、量化和权重大小参考 [Ollama Qwen3 标签页](https://ollama.com/library/qwen3/tags)。这些是可核查的入门选项，并不表示是最新或最优模型。换用其他支持 Ollama 结构化输出的指令模型也可以。

Gemma 4 候选的标签、量化和约 18 GB 下载大小见 [Ollama 模型页](https://ollama.com/library/gemma4:26b-a4b-it-q4_K_M)。该库模型尚未作为本项目的独立测试对象；24 GB 显存下也应先从较短上下文开始，给嵌入模型和运行时留出余量。

也可对照尝试 `gemma3:4b-it-q4_K_M`（4B，约 3.4 GB）、`gemma3:12b-it-q4_K_M`（12B，约 8.2 GB）、`gemma3:27b-it-q4_K_M`（27B，约 17 GB）。从较短上下文开始，保持深度思考关闭；该模型系列不提供本项目所说的推理开关能力。大小参考 [Ollama Gemma 3 标签页](https://ollama.com/library/gemma3/tags)。不同模型的性格遵循、情绪归属判断和 JSON 输出稳定性需要实际验证，换模型不会保证完全相同的表达。

**下载大小不等于实际显存占用。** 还需要 KV cache、运行时缓冲、桌面显示和嵌入模型空间。`bge-m3` 约 1.2 GB，负责跨语言记忆检索，不负责聊天，见[模型说明](https://ollama.com/library/bge-m3)。Ollama 可能加载、卸载或把模型部分放入系统内存，因此不能只用权重大小判断能否流畅运行。显存紧张时先缩短上下文、关闭深度思考，再换小模型；可在设置中关闭语义检索，届时使用关键词检索。

建议温度先用 `0.7`，输出上限先用 `1024`；本项目每轮还需要生成内部结构化字段，输出额度过小可能导致失败。小模型能启动不代表能可靠完成所有情绪和记忆任务。基础模型的使用条款由其发布者规定，代码的许可证不会覆盖模型权重。

### 手动启动 / macOS 与 Linux

Windows 一键脚本是当前自动安装入口。其他系统先安装 Python 3.11+ 和 [Ollama](https://ollama.com/download)，启动 Ollama 后，在项目根目录执行：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp examples/Modelfile.example Modelfile  # 按需编辑；已有文件时不要覆盖
.venv/bin/python scripts/bootstrap.py
```

Windows 已有环境也可直接运行：

```powershell
.\.venv\Scripts\python.exe scripts/bootstrap.py
```

首次初始化后，平时可直接启动 `python app/backend/web_server.py`；此方式不会自动重建 Modelfile 或下载依赖。CLI 为 `python app/backend/main.py`。

### 架构与演示

一次对话的主要路径：

```text
用户消息 → 生成队列 → 相关记忆 + 当前情绪 + 自定义人格
        → 模型结构化输出 → 回复质量 / 语言检查
        → 情绪共鸣与变化合并 → 持久状态 → 下一轮上下文
```

记忆具有评分、强化、有效期和语义 / 关键词检索。当前“遗忘”意味着标记为失效并停止检索，原始记录仍保留；它不等于隐私数据的永久删除。

主动想法也走生成队列；已开始的主动生成先完成，再处理排队的用户消息。无新内容可跳过；文本检查会拦截明显重复。详见 [主动发言](docs/spontaneous-thoughts.md) 和 [情绪与共鸣](docs/emotions.md)。长期方向目前是提示词背景，没有自主训练或目标达成评估。

工作演示版 `/demo` 每次新聊天选择 T0–T3，使用独立的临时会话情绪，不加载个人提示词、聊天和记忆。演示使用通用关系说明，不展示使用者自定义的私人角色。T0 演示口令默认 `0423`，可用 `MATISSE_DEMO_T0_PASSWORD` 修改。

当前是绑定 `127.0.0.1` 的本机单用户程序，演示口令不是整站登录机制；没有面向公网的多用户隔离和认证。

### 生成公开源码包

不要直接上传个人工作目录。在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe scripts/prepare_release.py
```

脚本使用明确的公开文件清单生成 `dist/matisse-source-时间.zip`，只包含代码、测试、通用示例和文档；不会读取或复制真实 `config/`、`repository/`、`Modelfile`、模型和头像。新增公开文件需显式加入清单。`.gitignore` 同时排除本地私人文件，但它不会清理已经进入 Git 历史的内容。

发行包仍需在发布前检查；当前生成的是发布候选包。

### 许可证与模型

本项目原创代码及随附文档采用 [MIT License](LICENSE)。允许使用、修改、分发和商业使用，也允许将修改后的版本闭源；分发本软件或其实质性部分时，须保留版权和许可声明。软件按原样提供，不提供担保，完整条款见 `LICENSE`。

欢迎公开分享你的改进，但不作强制要求。

本仓库不包含大语言模型权重、嵌入模型权重或作者的私人角色设定、聊天记录、记忆及其他个人运行数据。未随本项目发布的私人内容不属于本次授权范围。

第三方组件仍遵循各自的许可证。使用者须自行获取模型，并遵守相应模型及服务的许可条款；本项目的 MIT License 不授予第三方模型或组件的任何额外权利。

### 验证

```powershell
python -m unittest discover -s tests -p "test_*.py"
node tests/test_frontend_thoughts.cjs
node tests/test_frontend_sadness.cjs
node tests/test_frontend_memories.cjs
node tests/test_frontend_demo.cjs
node tests/test_frontend_language.cjs
node tests/test_frontend_personality.cjs
```

Node.js 只用于前端测试，正常使用不需要安装。自动测试使用隔离目录与模拟模型，不会读取个人聊天或调用真实大模型。实际内容质量、硬件性能和安装网络条件需要另外实测。

[返回语言选择](#matisse) · [English](#english)
