请分析这张机械零件图纸，按照以下 JSON Schema 提取所有信息：

```
{
  "basic_info": {
    "part_name": "零件名称（从标题栏或主要标注提取）",
    "drawing_number": "图纸编号（通常在标题栏右下角）",
    "material": "材料牌号和名称（如：45# 优质碳素结构钢）",
    "surface_treatment": "表面处理方式（如：发黑处理、镀锌等，无则写'无'）"
  },
  "dimensions": {
    "length": 长度（mm，仅数字）,
    "width": 宽度（mm，仅数字）,
    "height_thickness": 高度或厚度（mm，仅数字）,
    "other_dimensions": "其他重要尺寸说明（可选，如倒角、圆角等）"
  },
  "tolerances": [
    {
      "dimension_name": "尺寸名称（如：轴径、孔径、总长等）",
      "basic_size": 基本尺寸（仅数字）,
      "tolerance_code": "公差代号（如h7、f8，无则null）",
      "upper_deviation": 上偏差（仅数字，无则0）,
      "lower_deviation": 下偏差（仅数字）
    }
  ],
  "geometric_tolerances": [
    {
      "item": "形位公差项目（如：同轴度、垂直度、平行度等）",
      "value": 公差值（仅数字，mm）
    }
  ],
  "surface_roughness": [
    {
      "surface_location": "表面位置（如：配合面、非配合面、轴颈等）",
      "value": 粗糙度值（仅数字，如1.6表示Ra1.6μm）
    }
  ],
  "technical_requirements": [
    "技术要求1（如：未注倒角C1）",
    "技术要求2（如：锐边倒钝）",
    "技术要求3"
  ]
}
```

提取规则：
1. 数值字段必须是纯数字，不含单位符号
2. 所有尺寸单位统一为 mm
3. 粗糙度值仅提取数字部分（如 Ra1.6 → 1.6）
4. 缺失信息用空数组 [] 或 null 表示
5. 只返回 JSON，不需要任何解释或额外文本