# Qwen2.5 1.5B Instruct

本目录随项目携带 Qwen 发布的 Q4_K_M GGUF 权重。文件保留上游内容，使用 Apache 2.0 许可，见 [LICENSE](LICENSE)。 [Qwen 官方模型文件](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/blob/main/qwen2.5-1.5b-instruct-q4_k_m.gguf)

| 项目 | 值 |
| --- | --- |
| 权重 | `qwen2.5-1.5b-instruct-q4_k_m.gguf` |
| 大小 | 1,117,320,736 字节 |
| SHA-256 | `6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e` |
| Ollama 标签 | `qwen2.5:1.5b` |

Git 通过 LFS 跟踪 GGUF。从含有 LFS 对象的远程仓库克隆后，可运行 `git lfs pull` 取回实际文件。通过压缩包交付时，请包含完整 GGUF、`Modelfile` 和 `LICENSE`。

已安装并启动 Ollama 时，也可从仓库根目录手动导入。

```powershell
ollama create qwen2.5:1.5b -f .\models\Modelfile
```
