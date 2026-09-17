import logging
import os.path

import yaml

log = logging.getLogger(__name__)

SKILL_DIR = os.path.join(os.path.dirname(__file__),"definitions")

class SkillMeta:
    #skill元数据
    def __init__(self, name:str,description:str,tags:list[str],
                 required_tools:list[str],file_path:str):
        self.name = name
        self.description = description
        self.tags = tags
        self.required_tools = required_tools
        self.file_path = file_path

class SkillRegistry:
    def __init__(self):
        self._skills:dict[str:SkillMeta] = {}
        self._scan()
    def _scan(self):
        if not os.path.isdir(SKILL_DIR):
            log.warning("Skill 目录不存在:%s", SKILL_DIR)
            return
        for filename in os.listdir(SKILL_DIR):
            if not filename.endswith(".md"):
                continue
            filePath = os.path.join(SKILL_DIR,filename)
            try:
                meta = self._parse_meta(filePath)
                self._skills[meta.name] = meta
                log.info("注册skill:%s (%s)",meta.name,meta.description)
            except Exception as e:
                log.warning("解析 Skill 失败 [%s]: %s",  filename, e)

        log.info("已注册 %d 个技能", len(self._skills))
    def _parse_meta(self,filePath:str)->SkillMeta:
        with open(filePath, "r", encoding="utf-8") as f:
            content = f.read()

        if not content.startswith("---"):
            raise ValueError("无效的 Skill 文件")

        parts = content.split("---",2)

        if len(parts)<3:
            raise ValueError("front-matter 格式错误")
        meta = yaml.safe_load(parts[1])
        return SkillMeta(
            name = meta["name"],
            description = meta["description"],
            tags = meta["tags"],
            required_tools = meta["required_tools"],
            file_path = filePath
        )
    def get_catalog(self)->str:
        """
        生成 Skill 目录文本，注入 Planner 的 System Prompt。
        只包含名称和描述，不包含完整内容。
        """
        if not self._skills:
            return "暂无可用 Skill"
        lines = []
        for s in self._skills.values():
            lines.append(f"- {s.name}: {s.description}")
        return "\n".join(lines)
    def get_content(self,name:str)->str:
        """按需加载 Skill 的完整内容（去掉 front-matter）"""
        skill = self._skills.get(name)
        if not skill:
            return ""
        with open(skill.file_path, "r", encoding="utf-8") as f:
            content = f.read()
        # 去掉 front-matter，只返回正文
        parts = content.split("---", 2)
        return parts[2].strip() if len(parts) >= 3 else content

    def get_required_tools(self,name:str)->list[str]:
        """获取 Skill 所需的工具列表"""
        skill = self._skills.get(name)
        return skill.required_tools if skill else []

    def get_meta(self, name: str) -> SkillMeta | None:
        return self._skills.get(name)
skill_registry = SkillRegistry()