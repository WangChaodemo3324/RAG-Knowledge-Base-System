# RAG Python 3.12 + Torch 2.6 Environment

This project keeps the old `pytorch` environment untouched and creates a new
environment for Python 3.12 and PyTorch 2.6.

## Target

- Environment path: `E:\Anaconda3\envs\rag-py312-torch26`
- Python: `3.12`
- PyTorch: `2.6.0`
- CUDA wheel: `cu124`

## Create

```powershell
& 'D:\ProgramData\anaconda3\Scripts\conda.exe' create -p 'E:\Anaconda3\envs\rag-py312-torch26' python=3.12 pip -y
& 'E:\Anaconda3\envs\rag-py312-torch26\python.exe' -m pip install torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124
& 'E:\Anaconda3\envs\rag-py312-torch26\python.exe' -m pip install -r 'env_specs\requirements-rag-py312.txt'
```

## Verify

```powershell
& 'E:\Anaconda3\envs\rag-py312-torch26\python.exe' -c "import sys, torch; print(sys.version); print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
& 'E:\Anaconda3\envs\rag-py312-torch26\python.exe' -m uvicorn api:app --host 127.0.0.1 --port 8013
```
