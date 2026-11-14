from pathlib import Path

from langchain_community.document_loaders import TextLoader

BASE_DIR = Path(__file__).resolve().parent.parent
loader = TextLoader(str(BASE_DIR / "resource data" / "生产环境发布与回滚操作规范.md"), encoding="utf-8")
documents = loader.load()

from langchain_text_splitters import RecursiveCharacterTextSplitter
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=128,  # 根据嵌入模型调整（如text-embedding-ada-002支持8191）
    chunk_overlap=50,
    separators=["\n\n", "\n", "。",  "！", "？","//"]  # 优化分隔符
)

texts = text_splitter.create_documents([documents[0].page_content],metadatas=[documents[0].metadata])


from langchain_community.embeddings import HuggingFaceBgeEmbeddings
from langchain_community.vectorstores import Chroma
import os

model_kwargs = {'device': 'cpu'}  # 使用CPU
encode_kwargs = {'normalize_embeddings': True}  # 标准化嵌入向量

local_embedding_model = (
    Path.home()
    / ".cache"
    / "huggingface"
    / "hub"
    / "models--moka-ai--m3e-small"
    / "snapshots"
    / "44c696631b2a8c200220aaaad5f987f096e986df"
)
embedding_model_name = str(local_embedding_model) if local_embedding_model.exists() else "moka-ai/m3e-small"

# 创建embedding模型实例
embedding = HuggingFaceBgeEmbeddings(
    model_name=embedding_model_name,
    model_kwargs=model_kwargs,
    encode_kwargs=encode_kwargs,
    query_instruction="为文本生成向量表示用于文本检索"  # M3E模型不需要特定指令，但保留不影响
)


# 加载数据到Chroma数据库
db = Chroma.from_documents(texts, embedding)
# similarity search
search_result = db.similarity_search("生产环境什么时候必须回滚？")
print("=== 检索结果（生产环境什么时候必须回滚？）===")
for i, doc in enumerate(search_result):
    print(f"[{i+1}] {doc.page_content[:200]}...")


from langchain.memory import ConversationBufferMemory
from langchain.chains import ConversationalRetrievalChain
from langchain_openai import ChatOpenAI

# 如需直接写在代码里，把下面三个值改掉即可。
# 环境变量优先级更高：DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL / DEEPSEEK_MODEL
DEEPSEEK_API_KEY = ""  # 不要把真实 Key 写进代码，请放到 .env：DEEPSEEK_API_KEY=sk-xxxx
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-v4-flash"

api_key = os.getenv("DEEPSEEK_API_KEY") or DEEPSEEK_API_KEY
base_url = os.getenv("DEEPSEEK_BASE_URL") or DEEPSEEK_BASE_URL
model_name = os.getenv("DEEPSEEK_MODEL") or DEEPSEEK_MODEL

if not api_key:
    print("\n未设置 DEEPSEEK_API_KEY，已跳过大模型问答调用。")
    print("如需启用问答，请先在 PowerShell 设置：")
    print('$env:DEEPSEEK_API_KEY="你的 DeepSeek API Key"')
    raise SystemExit(0)

llm = ChatOpenAI(
    model=model_name, # 使用 DeepSeek OpenAI 兼容接口
    temperature=0,
    max_tokens=None,
    timeout=60,
    max_retries=2,
    api_key=api_key,
    base_url=base_url,
    # organization="...",
    # other params...
)
retriever = db.as_retriever()
memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
qa = ConversationalRetrievalChain.from_llm(llm, retriever, memory=memory)
result = qa.invoke({"question": "生产环境什么时候必须回滚？"})
print("\n=== 问答结果 ===")
print("问题:", result.get("question"))
print("答案:", result.get("answer"))
