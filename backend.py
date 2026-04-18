from dataclasses import dataclass, asdict
import os, uuid, json
from dotenv import load_dotenv
import inspect
from datetime import datetime
import oss2
from io import BytesIO
from PIL import Image
from flask import Flask, request, jsonify
import json
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from openai import OpenAI

# 从配置文件 main_prompt.md 中读取 Prompt
def loadPrompts():
    with open("main_prompt.md", "r", encoding="utf-8") as f:
        return f.read()
_MainPrompt = loadPrompts()

# Logger 类
class Logger:
    @staticmethod
    def _log(level: str, message: str):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        caller = inspect.stack()[2]
        # line = caller.lineno
        print(f"[{now}] [{level}] {message}")

    @classmethod
    def info(cls, message: str):
        cls._log("INFO", message)

    @classmethod
    def warning(cls, message: str):
        cls._log("WARNING", message)

    @classmethod
    def error(cls, message: str):
        cls._log("ERROR", message)

# 后端配置文件
# 请通过 .env 文件设置相关环境变量
class BackendConfig:
    OSS_ENDPOINT = ""
    OSS_ACCESS_KEY = ""
    OSS_ACCESS_SECRET = ""
    OSS_BUCKET_NAME = ""
    OPENAI_API_KEY = ""
    OPENAI_API_BASE = ""
    OPENAI_MODEL = ""
    OPENAI_MAX_TOKENS = ""

    def load(self):
        Logger.info("正在开始从 .env 文件加载环境变量...")
        load_dotenv()
        cls = self.__class__
        not_satisfied = 0
        for name, value in vars(cls).items():
            if name.startswith("__") or callable(value):
                continue
            if name not in os.environ:
                Logger.error(f"环境变量 {name} 未设置!")
                not_satisfied += 1
            else:
                setattr(self, name, os.environ[name])
                Logger.info(f"环境变量 {name} --> {os.environ[name]}")
        if not_satisfied >= 1:
            Logger.error(f"{not_satisfied} 个环境变量未设置, 即将退出")
            exit(1)

class OSSOperation:
    bucket = None
    def initBucket(self, config: BackendConfig):
        auth = oss2.Auth(config.OSS_ACCESS_KEY, config.OSS_ACCESS_SECRET)
        bucket = oss2.Bucket(auth, endpoint=config.OSS_ENDPOINT, bucket_name=config.OSS_BUCKET_NAME)
        self.bucket = bucket
    def getBucket(self):
        if self.bucket == None:
            raise ValueError("在存储桶还未初始化时就调用")
        return self.bucket
    def testBucket(self):
        """
        测试是否能连接到配置的 OSS 存储桶。
        """
        try:
            self.getBucket().get_bucket_info()
            Logger.info("成功连接到 OSS 存储桶")
        except Exception as e:
            Logger.error("无法连接到 OSS 存储桶，请检查配置!")
            raise e
    def getPathOf(self, convID: str, imageID: str):
        """
        获得指定对话的指定图像 URL。

        :param convID: 本次对话的 UUID 字符串
        :param imageID: 该图像的 UUID 字符串
        """
        path = f"{convID}/{imageID}.jpg"
        return "https://draftmind.oss-cn-beijing.aliyuncs.com" + "/" + path
    def upload(self, convID: str, content):
        """
        上传一个图像到阿里云 OSS，并返回一个永久对象的 URL 以供模型后期调用。

        :param convID: 本次对话的 UUID 字符串
        :param content: 文件路径, 文件 Reader, 或文件内容（必须是一个图像）

        :return: 该图像的URL。
        """
        if isinstance(content, str):
            with open(content, "rb", encoding="utf-8") as f:
                content = f.read()
        elif hasattr(content, "read"):
            content = content.read()

        # 将图片转为 JPEG 格式，并保存在内存中
        image = Image.open(BytesIO(content))
        if image.format != "JPEG":
            with BytesIO() as output:
                image.convert("RGB").save(output, format="JPEG")
                content = output.getvalue()

        fileID = str(uuid.uuid4())
        path = f"{convID}/{fileID}.jpg"
        self.getBucket().put_object(path, content)
        return "https://draftmind.oss-cn-beijing.aliyuncs.com" + "/" + path

# -------------------------------------------
# 下列代码定义的是 AI 识别出来的图纸信息

@dataclass
class BasicInfo:
    part_name: str
    drawing_number: str
    material: str
    surface_treatment: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BasicInfo':
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'part_name': self.part_name,
            'drawing_number': self.drawing_number,
            'material': self.material,
            'surface_treatment': self.surface_treatment
        }

    def to_json(self, ensure_ascii: bool = False, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=ensure_ascii, indent=indent)

@dataclass
class Dimensions:
    length: float
    width: float
    height_thickness: float
    other_dimensions: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Dimensions':
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'length': self.length,
            'width': self.width,
            'height_thickness': self.height_thickness,
            'other_dimensions': self.other_dimensions
        }

    def to_json(self, ensure_ascii: bool = False, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=ensure_ascii, indent=indent)

@dataclass
class Tolerance:
    dimension_name: str
    basic_size: float
    upper_deviation: float
    lower_deviation: float
    tolerance_code: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Tolerance':
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'dimension_name': self.dimension_name,
            'basic_size': self.basic_size,
            'upper_deviation': self.upper_deviation,
            'lower_deviation': self.lower_deviation,
            'tolerance_code': self.tolerance_code
        }

    def to_json(self, ensure_ascii: bool = False, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=ensure_ascii, indent=indent)

@dataclass
class GeometricTolerance:
    item: str
    value: float

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'GeometricTolerance':
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'item': self.item,
            'value': self.value
        }

    def to_json(self, ensure_ascii: bool = False, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=ensure_ascii, indent=indent)

@dataclass
class SurfaceRoughness:
    surface_location: str
    value: float

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SurfaceRoughness':
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'surface_location': self.surface_location,
            'value': self.value
        }

    def to_json(self, ensure_ascii: bool = False, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=ensure_ascii, indent=indent)

@dataclass
class PartDrawing:
    basic_info: BasicInfo
    dimensions: Dimensions
    tolerances: List[Tolerance] = field(default_factory=list)
    geometric_tolerances: List[GeometricTolerance] = field(default_factory=list)
    surface_roughness: List[SurfaceRoughness] = field(default_factory=list)
    technical_requirements: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PartDrawing':
        basic_info = BasicInfo.from_dict(data.get('basic_info', {}))
        dimensions = Dimensions.from_dict(data.get('dimensions', {}))
        
        tolerances = [Tolerance.from_dict(t) for t in data.get('tolerances', [])]
        geometric_tolerances = [GeometricTolerance.from_dict(gt) for gt in data.get('geometric_tolerances', [])]
        surface_roughness = [SurfaceRoughness.from_dict(sr) for sr in data.get('surface_roughness', [])]
        technical_requirements = data.get('technical_requirements', [])

        return cls(
            basic_info=basic_info,
            dimensions=dimensions,
            tolerances=tolerances,
            geometric_tolerances=geometric_tolerances,
            surface_roughness=surface_roughness,
            technical_requirements=technical_requirements
        )

    @classmethod
    def from_json(cls, json_str: str) -> 'PartDrawing':
        data = json.loads(json_str)
        return cls.from_dict(data)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'basic_info': self.basic_info.to_dict(),
            'dimensions': self.dimensions.to_dict(),
            'tolerances': [t.to_dict() for t in self.tolerances],
            'geometric_tolerances': [gt.to_dict() for gt in self.geometric_tolerances],
            'surface_roughness': [sr.to_dict() for sr in self.surface_roughness],
            'technical_requirements': self.technical_requirements
        }

    def to_json(self, ensure_ascii: bool = False, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=ensure_ascii, indent=indent)
    
# -------------------------------------------
    
@dataclass
class DraftInformation:
    # 图纸标题
    title: str = ""
    # 图纸编号（通常在标题栏右下角）
    draft_number: str = ""
    pass

class AIConversation:
    """
    本 class 内定义了一个单独的 AI 上下文
    即从一开始上传图纸、生成信息、到用户询问聊天记录的所有信息
    """
    # 被保护的上下文，通常是和图片文件有关的上下文，dict 列表
    main_contents = []
    # 用户对图片询问的上下文
    ask_contents = []
    # 已识别的图像信息
    information = DraftInformation()

    def getFullContext(self):
        """ 获取完整上下文 """
        return [*self.main_contents, *self.ask_contents]
    def clearQuestions(self):
        """ 重置用户提问上下文 """
        self.ask_contents = []
    def setInformation(self, info):
        """ 设置图像信息 """
        self.information = info
    def getInformation(self):
        """ 获取图像信息 """
        return self.information
    def getDict(self):
        return {
            "info": asdict(self.information),
            "main_contents": self.main_contents,
            "ask_contents": self.ask_contents
        }

    @staticmethod
    def fromJSON(json_data: dict):
        """ 从 JSON 数据创建一个 AIConversation 对象 """
        conv = AIConversation()
        conv.main_contents = json_data.get("main_contents", [])
        conv.ask_contents = json_data.get("ask_contents", [])
        conv.information = DraftInformation(**json_data.get("info", dict()))
        return conv
    
class ConvStore:
    """
    本 class 代表了所有上下文的存储器，负责将所有聊天记录序列化和保存到文件中。
    """
    conversations: dict[str, AIConversation] = dict()
    uuid_to_title: dict[str, str] = dict()
    def getConversationOf(self, uuid: str):
        return self.conversations[uuid]
    def addConversation(self):
        """
        新建一个对话上下文。通常是在用户开始上传新的图纸图片时开始。
        """
        conv_uuid = str(uuid.uuid4())
        self.conversations[conv_uuid] = AIConversation()
        return conv_uuid
    def saveToFile(self):
        """ 将当前所有对话上下文保存到磁盘文件中 """
        directionary_path = "./conversations"
        os.makedirs(directionary_path, exist_ok=True)
        for conv_uuid, conv in self.conversations.items():
            with open(os.path.join(directionary_path, f"{conv_uuid}.json"), "w") as f:
                # store JSON
                json.dump(conv.getDict(), f, ensure_ascii=False, indent=4)
        # 把所有 conversations 的 UUID 及其 title 的关系保存到一个单独的文件中，方便前端展示
        with open(os.path.join(directionary_path, "index.json"), "w") as f:
            index_data = {conv_uuid: conv.getInformation().title for conv_uuid, conv in self.conversations.items()}
            json.dump(index_data, f, ensure_ascii=False, indent=4)
        
    def loadFromFile(self):
        """ 从磁盘文件中加载对话上下文 """
        directionary_path = "./conversations"
        if not os.path.exists(directionary_path):
            Logger.warning("./conversations 文件夹不存在，正在创建...")
            os.mkdir(directionary_path)
            return
        for filename in os.listdir(directionary_path):
            if filename.endswith(".json"):
                conv_uuid = filename[:-5]
                with open(os.path.join(directionary_path, filename), "r") as f:
                    json_data = json.load(f)
                    Logger.info(f"从文件中加载了 {conv_uuid}")
                    self.conversations[conv_uuid] = AIConversation.fromJSON(json_data)
        # 加载 UUID 到 title 的映射
        index_path = os.path.join(directionary_path, "index.json")
        if os.path.exists(index_path):
            with open(index_path, "r") as f:
                self.uuid_to_title = json.load(f)
        else:
            Logger.warning("index.json 文件不存在，无法加载 UUID 到 title 的映射")

class OpenAIImpl:
    """
    OpenAI 实现类，负责与 OpenAI API 进行交互。
    """
    def __init__(self, config: BackendConfig):
        self.api_key = config.OPENAI_API_KEY
        self.api_base = config.OPENAI_API_BASE
        self.model = config.OPENAI_MODEL
        self.max_tokens = int(config.OPENAI_MAX_TOKENS)
        self.client = OpenAI(api_key=self.api_key, base_url=self.api_base)
    
    def getResponse(self, prompt: str, conversation: AIConversation, direction: str, image_url: Optional[str] = None):
        """
        根据当前对话上下文，向 OpenAI API 发送请求，并返回模型的回复。
        结合 AIConversation 构建上下文。
        """

        if image_url:
            new_message = {"role": "user", "content": [{"type": "image_url", "image_url": {"url": image_url}}, {"type": "text", "text": prompt}]}
        final_new_message = ([new_message] if image_url else [{"role": "user", "content": prompt}])
        response = self.client.chat.completions.create(
            model=self.model,
            messages=conversation.getFullContext() + final_new_message,
            max_tokens=self.max_tokens
        )
        # 把 AI 的回复添加到 conversation 的不同 context 中，供后续对话使用
        context = final_new_message + [{"role": "assistant", "content": response.choices[0].message.content}]
        Logger.info(f"将以下上下文添加到 conversation 中，direction={direction}:\n{json.dumps(context, ensure_ascii=False, indent=2)}")
        if direction == "main":
            conversation.main_contents.append(context)
        elif direction == "ask":
            conversation.ask_contents.append(context)
        return response.choices[0].message.content
        
        
config = BackendConfig()
config.load()
oss = OSSOperation()
oss.initBucket(config)

try:
    oss.testBucket()
except Exception as e:
    Logger.error("无法连接到 OSS 存储桶，程序无法继续运行!")
    exit(1)

conversations = ConvStore()
conversations.loadFromFile()
openai_impl = OpenAIImpl(config)

app = Flask(__name__)

@app.route("/")
def f_index():
    return "Hello, DraftMind Backend is running!"

@app.route("/conversation/list", methods=["GET"])
def f_list_conversations():
    """
    列出所有对话。
    响应示例：
    
    ```
    {
        "对话的UUID": "图纸的标题",
        "对话的UUID2": "图纸的标题2",
        ...
    }
    ```
    """
    return jsonify(conversations.uuid_to_title)

@app.route("/conversation/new", methods=["POST"])
def f_new_conversation():
    global oss, conversations, openai_impl
    """
    新建一个对话，要求附带图纸的图片 (JPG 格式)。
    后端将向 AI 模型发送该图纸图片，并从模型返回的对话上下文中提取图纸信息（如标题、格式等）
    存储该对话上下文，并返回该对话的 UUID 以供后续查询。
    """
    if "image" not in request.files:
        return jsonify({"error": "没有上传图纸图片"}), 400
    image_file = request.files["image"]
    content = image_file.read()
    conv_uuid = conversations.addConversation()
    image_url = oss.upload(conv_uuid, content)
    Logger.info(f"已上传图纸图片，URL: {image_url}")
    # 构建一个 prompt，要求模型分析图纸图片，并提取图纸信息
    # 使用 main_prompt.md 中的 Prompt，同时加入图像以供分析（注意需要特定格式）
    prompt = _MainPrompt
    response = openai_impl.getResponse(prompt, conversations.getConversationOf(conv_uuid), "main", image_url=image_url)
    if response == None:
        return jsonify({"error": "模型没有返回有效的回复"}), 500
    Logger.info(f"模型回复: {response}")

    # 检查是否是 JSON 格式的回复，如果不是，则返回错误
    try:
        json_response = json.loads(response)
    except ValueError:
        return jsonify({"error": "模型回复的格式不正确，无法解析为 JSON", "raw_response": response}), 500
    
    # 从 response 中提取图纸 JSON 到 PartDrawing 对象
    part_drawing = PartDrawing.from_json(response)
    
    # 将分析的 PartDrawing 对象中的基本信息（如标题、图纸编号）设置到 conversation 的 information 中，供后续查询使用
    conversations.getConversationOf(conv_uuid).setInformation(DraftInformation(title=part_drawing.basic_info.part_name, draft_number=part_drawing.basic_info.drawing_number))

    # 保存分析结果
    conversations.saveToFile()

    # 将 PartDrawing 对象中的信息保存到 drawing_data 文件夹的 uuid.json 文件中
    drawing_data_path = "./drawing_data"
    os.makedirs(drawing_data_path, exist_ok=True)
    with open(os.path.join(drawing_data_path, f"{conv_uuid}.json"), "w") as f:
        f.write(part_drawing.to_json())
    return jsonify({"conv_uuid": conv_uuid})
    
@app.route("/conversation/<conv_uuid>/context", methods=["GET"])
def f_get_conversation_context(conv_uuid):
    """
    获取指定 UUID 的对话上下文。
    响应示例：
    ```
    OpenAI 格式的对话上下文, 但只包含用户提问的上下文
    ```
    """
    conv = conversations.getConversationOf(conv_uuid)
    return jsonify(conv.ask_contents)

@app.route("/conversation/<conv_uuid>/info", methods=["GET"])
def f_get_conversation_info(conv_uuid):
    """
    获取指定 UUID 的对话解析的图纸信息。
    响应示例：
    ```
    PartDrawing JSON 数据，包含图纸的基本信息、尺寸信息、公差信息、技术要求等
    ```
    """
    drawing_data_path = "./drawing_data"
    json_path = os.path.join(drawing_data_path, f"{conv_uuid}.json")
    if not os.path.exists(json_path):
        return jsonify({"error": "指定 UUID 的图纸信息不存在"}), 404
    with open(json_path, "r", encoding="utf-8") as f:
        part_drawing_json = f.read()
    part_drawing = PartDrawing.from_json(part_drawing_json)
    return jsonify(part_drawing.to_dict())

if __name__ == "__main__":
    app.run(debug=True)