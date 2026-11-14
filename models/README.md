# 本地模型说明

仓库**不随附模型权重**。推荐使用 [Qwen2.5 1.5B Instruct](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF)（Apache 2.0 许可，见 [LICENSE](LICENSE)），通过 Ollama 拉取：

```powershell
ollama pull qwen2.5:1.5b
```

也可以手动下载 GGUF 后导入：

```powershell
# 从 Hugging Face 下载 qwen2.5-1.5b-instruct-q4_k_m.gguf 到本目录，然后：
ollama create qwen2.5:1.5b -f .\Modelfile
```

参考信息（Q4_K_M 量化）：

| 项目 | 值 |
| --- | --- |
| 文件 | `qwen2.5-1.5b-instruct-q4_k_m.gguf` |
| 大小 | 1,117,320,736 字节 |
| SHA-256 | `6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e` |
| Ollama 标签 | `qwen2.5:1.5b` |

`deploy.ps1 -DeployLocalModel` 会优先使用本目录中通过 SHA-256 校验的完整权重，否则自动执行 `ollama pull`。
