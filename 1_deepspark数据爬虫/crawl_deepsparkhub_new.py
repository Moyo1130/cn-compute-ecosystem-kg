import requests
import pandas as pd
import re
import os
import time
from urllib.parse import urlparse

# --- 配置 ---
API_BASE_URL = "https://gitee.com/api/v5"
REPO_PATH = "deep-spark/deepsparkhub"
REPO_HTML_URL = f"https://gitee.com/{REPO_PATH}"
MAX_DEPTH = 5

# --- 数据存储 ---
nodes, edges = {}, set()

# --- 辅助函数 ---
def get_unique_id(label, name):
    clean_name = re.sub(r'[^a-zA-Z0-9_-]', '', str(name)).lower()
    return f"{label.lower()}:{clean_name}"

def add_node(label, name, source_url="", extra={}):
    """添加节点,返回节点ID"""
    node_id = get_unique_id(label, name)
    if node_id not in nodes:
        node_data = {"id": node_id, "label": label, "name": name}
        if source_url:
            node_data["source_url"] = source_url
        # 根据节点类型添加特定属性
        if label == "SoftwareInstance":
            node_data["software_id"] = extra.get("software_id", "")
            node_data["framework_id"] = extra.get("framework_id", "")
        elif label == "DeploymentConfig":
            node_data["hardware_id"] = extra.get("hardware_id", "")
            node_data["runtime_id"] = extra.get("runtime_id", "")
        # 其他extra属性存储为额外字段
        for k, v in extra.items():
            if k not in ["software_id", "framework_id", "hardware_id", "runtime_id"]:
                node_data[f"extra/{k}"] = v
        nodes[node_id] = node_data
    return node_id

def add_edge(source_id, relation, target_id):
    edges.add((source_id, relation, target_id))

def infer_model_name_from_path(path):
    parts = path.split('/')
    return parts[-2] if len(parts) >= 2 else parts[-1]

def infer_main_task_from_path(path):
    parts = path.split('/')
    return parts[2] if len(parts) >= 3 else "N/A"

def get_software_source_url(path):
    """获取Software节点的source_url,移除最后一层框架路径"""
    parts = path.split('/')
    if len(parts) >= 2:
        software_path = '/'.join(parts[:-1])  # 移除最后一层框架
        return f"{REPO_HTML_URL}/tree/master/{software_path}"
    return f"{REPO_HTML_URL}/tree/master/{path}"

def get_application_area(path):
    path_lower = path.lower()
    if 'nlp' in path_lower or 'llm' in path_lower: return 'NLP'
    if 'cv' in path_lower or 'vision' in path_lower: return 'CV'
    if 'audio' in path_lower or 'speech' in path_lower: return 'Audio'
    if 'hpc' in path_lower: return 'HPC'
    return 'Other'

def infer_author_from_url(url):
    try:
        path_parts = urlparse(url).path.strip('/').split('/')
        if path_parts and len(path_parts) >= 1: return path_parts[0]
    except Exception as e:
        print(f"    - URL解析作者失败: {url}, error: {e}")
    return None

# --- 核心API与递归逻辑 ---
def robust_get_request(url, headers):
    max_retries = 3
    for i in range(max_retries):
        try:
            response = requests.get(url, headers=headers, timeout=20)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            print(f"\n!!!!!! 请求严重失败: {e} !!!!!!")
            if i < max_retries - 1:
                print(f"程序将休眠 5 分钟... (北京时间 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time() + 300))})")
                time.sleep(300)
                print("休眠结束，正在重试...")
            else:
                print(f"    - 所有重试均失败: {url}")
                return None

def make_api_request(endpoint, headers, params=None):
    url = f"{API_BASE_URL}{endpoint}"
    response = robust_get_request(url, headers=headers)
    return response.json() if response else None

def find_all_readme_locations(path, headers):
    print(f"  - 正在扫描目录: {path if path else '/'}")
    readme_locations, current_depth = [], len(path.split('/')) if path else 0
    page = 1
    while True:
        contents = make_api_request(f"/repos/{REPO_PATH}/contents/{path}", headers, params={'page': page})
        if not contents: break
        for item in contents:
            if item['name'].lower() == 'readme.md':
                readme_locations.append({'path': path, 'model_html_url': f"{REPO_HTML_URL}/tree/master/{path}", 'readme_download_url': item.get('download_url')})
                break
        if current_depth < MAX_DEPTH:
            for item in contents:
                if item['type'] == 'dir' and not item['name'].startswith('.'):
                    sub_locations = find_all_readme_locations(item['path'], headers)
                    if sub_locations: readme_locations.extend(sub_locations)
        elif path:
            print(f"    - 已达到最大深度 {MAX_DEPTH}，不再扫描 '{path}' 的子目录。")
        if len(contents) < 100: break
        page += 1
    return readme_locations

def parse_readme_content(download_url, headers):
    details = {'ref_name': None, 'ref_url': None, 'hardware': [], 'runtime': []}
    if not download_url: return details
    response = robust_get_request(download_url, headers=headers)
    if not response: return details
    content = response.text

    # 提取 References 部分
    references_section_match = re.search(r'##\s+References(.*?)(?=##\s+|$)', content, re.IGNORECASE | re.DOTALL)
    if section_content := references_section_match:
        if link_match := re.search(r'\[([^\]]+)\]\(([^)]+)\)', section_content.group(1)):
            details['ref_name'], details['ref_url'] = link_match.group(1).strip(), link_match.group(2).strip()

    # 提取硬件和运行时信息
    # 仅解析 ## Supported Environments 和 ## Model Preparation 之间的内容
    supported_env_match = re.search(r'##\s+Supported Environments(.*?)(?=##\s+Model Preparation|$)', content, re.IGNORECASE | re.DOTALL)
    if supported_env_match:
        relevant_content = supported_env_match.group(1)
        for line in relevant_content.splitlines():
            if line.strip().startswith('| BI-'):  # 判断是否以 "| BI-" 开头
                cols = [col.strip() for col in line.split('|') if col.strip()]  # 分割并去除空格
                if len(cols) >= 3:  # 确保至少有三个有效元素
                    hardware_name = cols[0]  # 第一个有效元素是硬件节点的名称
                    if len(hardware_name) <= 7:  # 限制硬件名称最多7个字符
                        runtime_name = f"IXUCA SDK {cols[1]}"  # 第二个元素拼接形成运行时节点的名称
                        release_version = cols[2]  # 第三个元素是运行时节点的 release 属性
                        details['hardware'].append(hardware_name)
                        details['runtime'].append({'name': runtime_name, 'release': release_version})
    return details

# --- 【已修正的功能】确保扫描所有表格 ---
def parse_main_readme_for_enrichment(headers):
    """【已修正】使用精确的行检测逻辑解析主README中的所有模型库表格"""
    print("  - 正在下载并解析主 README.md...")
    main_readme_url = f"https://gitee.com/{REPO_PATH}/raw/master/README.md"
    enrichment_data = {}
    response = robust_get_request(main_readme_url, headers)
    if not response:
        print("  - 严重错误：无法下载主 README.md，跳过数据增强步骤。")
        return enrichment_data
    
    lines = response.text.strip().split('\n')
    processed_indices = set() # 用于跟踪已处理的行，避免重复解析

    # 【关键逻辑修正】外层循环会遍历所有行，寻找多个表头
    for i, line in enumerate(lines):
        if i in processed_indices:
            continue
            
        if "| Model" in line:
            print(f"  - 在第 {i+1} 行找到一个模型库表头，开始解析该表格...")
            
            # 内层循环解析数据行
            for j, data_row in enumerate(lines[i + 2:]):
                current_index = i + 2 + j
                
                if not data_row.strip().startswith('|'):
                    print(f"  - 在第 {current_index + 1} 行检测到表格结束，此表格解析完毕。")
                    break # 跳出内层循环，外层循环继续寻找下一个表头
                    
                processed_indices.add(current_index) # 标记此行为已处理
                
                cols = [c.strip() for c in data_row.split('|') if c.strip()]
                if len(cols) >= 3:
                    try:
                        model_name_match = re.search(r'\[([^\]]+)\]', cols[0])
                        if not model_name_match: continue
                        model_name = model_name_match.group(1).strip()
                        dataset = cols[2]
                        sdk_version = cols[-1]
                        enrichment_data[model_name] = {'dataset': dataset, 'sdk_version': sdk_version}
                    except IndexError:
                        print(f"  - 警告：解析主 README 表格时跳过不规范的行: {data_row}")
                        continue

    print(f"  - 解析完成，从主 README 中提取到 {len(enrichment_data)} 条模型增强信息。")
    return enrichment_data

def main():
    """主函数"""
    print(f"--- 启动 DeepSparkHub 全局爬虫程序 (v11 - 多表格解析修正) ---")
    gitee_token = os.getenv("GITEE_TOKEN")
    if not gitee_token:
        print("严重错误: 必须设置 GITEE_TOKEN 环境变量。")
        return
    headers = {"Authorization": f"token {gitee_token}"}
    print("检测到 GITEE_TOKEN，将使用认证模式访问 API。")

    print("\n步骤 1: 添加基础/回退节点...")
    fallback_author_id = add_node("Author", "DeepSpark Community", "https://gitee.com/deep-spark")
    framework_urls = {'pytorch': 'https://pytorch.org/', 'paddlepaddle': 'https://www.paddlepaddle.org.cn/', 'tensorflow': 'https://www.tensorflow.org/', 'mindspore': 'https://www.mindspore.cn/'}
    print("基础节点添加完毕。")

    print(f"\n步骤 2: 从根目录开始全局扫描 (深度不超过 {MAX_DEPTH})...")
    all_models_info = find_all_readme_locations("models", headers)
    if not all_models_info:
        print("错误: 未能找到任何符合条件的模型目录。")
        return
    print(f"\n扫描完成! 共发现 {len(all_models_info)} 个模型实现。")

    print("\n步骤 3: 依次处理每个发现的模型...")
    for model_info in all_models_info:
        model_path = model_info['path']
        if not model_path: continue
        model_name = infer_model_name_from_path(model_path)
        print(f"  - 正在处理模型 '{model_name}' (路径: {model_path})")
        readme_details = parse_readme_content(model_info['readme_download_url'], headers)
        area = get_application_area(model_path)
        main_task = infer_main_task_from_path(model_path)
        
        # 创建Software节点(抽象层)
        software_source_url = get_software_source_url(model_path)
        software_id = add_node("Software", model_name, software_source_url, 
                              extra={"Type": "模型", "area": area, "Main-Task": main_task})
        
        # 创建Framework节点
        framework_name = model_path.split('/')[-1]
        framework_url = framework_urls.get(framework_name.lower())
        if not framework_url:
            continue
        framework_id = add_node("Framework", framework_name.capitalize(), framework_url)
        
        # 创建SoftwareInstance节点(具体层)
        instance_name = f"{model_name}_{framework_name.capitalize()}"
        instance_id = add_node("SoftwareInstance", instance_name, model_info['model_html_url'],
                              extra={"software_id": software_id, "framework_id": framework_id})
        
        # 建立关系
        add_edge(instance_id, "INSTANCE_OF", software_id)
        add_edge(instance_id, "USES_FRAMEWORK", framework_id)
            
        # 创建硬件、运行时和部署配置节点
        hardware_runtime_pairs = []
        for i, hardware_name in enumerate(readme_details['hardware']):
            hardware_id = add_node("Hardware", hardware_name, "", extra={"Vendor": "天数智芯"})
            print(f"    - 已创建 Hardware 节点: {hardware_name}")
            
            if i < len(readme_details['runtime']):
                runtime_info = readme_details['runtime'][i]
                runtime_name = runtime_info['name']
                release_version = runtime_info['release']
                runtime_id = add_node("Runtime", runtime_name, "", extra={"release": release_version})
                print(f"    - 已创建 Runtime 节点: {runtime_name}, Release: {release_version}")
                
                # 创建硬件-运行时的关系
                add_edge(hardware_id, "SUPPORTS_RUNTIME", runtime_id)
                
                # 创建DeploymentConfig节点
                config_name = f"{hardware_name}_{runtime_name}"
                config_id = add_node("DeploymentConfig", config_name, "",
                                    extra={"hardware_id": hardware_id, "runtime_id": runtime_id})
                add_edge(config_id, "CONFIGURES_HARDWARE", hardware_id)
                add_edge(config_id, "CONFIGURES_RUNTIME", runtime_id)
                
                # SoftwareInstance可以在此DeploymentConfig上部署
                add_edge(instance_id, "CAN_DEPLOY_ON", config_id)
                print(f"    - 已创建 DeploymentConfig: {config_name}")

        # 处理作者信息
        author_id_to_link = fallback_author_id
        if readme_details['ref_url']:
            inferred_author = infer_author_from_url(readme_details['ref_url'])
            if inferred_author:
                hostname = urlparse(readme_details['ref_url']).hostname
                author_url = f"https://{hostname}/{inferred_author}"
                author_id_to_link = add_node("Author", inferred_author, author_url)
            elif readme_details['ref_name']:
                author_id_to_link = add_node("Author", readme_details['ref_name'], readme_details['ref_url'])
        add_edge(software_id, "DEVELOPED_BY", author_id_to_link)
        
        # 处理教程文档
        guide_id = add_node("Guide", f"{model_name} README", model_info['readme_download_url'])
        add_edge(instance_id, "HAS_GUIDE", guide_id)

    print("\n步骤 4: [数据增强] 从主 README 解析官方数据...")
    enrichment_data = parse_main_readme_for_enrichment(headers)
    for model_name, attributes in enrichment_data.items():
        software_id = get_unique_id("Software", model_name)
        if software_id in nodes:
            print(f"  - 正在增强模型 '{model_name}'...")
            dataset_name = attributes.get('dataset')
            if dataset_name and dataset_name != '-':
                dataset_id = add_node("Dataset", dataset_name, "")
                # 查找该Software对应的所有SoftwareInstance
                for node_id, node_data in nodes.items():
                    if node_data.get("label") == "SoftwareInstance" and node_data.get("software_id") == software_id:
                        add_edge(node_id, "TRAINED_ON", dataset_id)
                        print(f"    - 已关联 Dataset: {dataset_name} 到 {node_data['name']}")
    
    print("\n步骤 5: 将数据写入CSV文件...")
    nodes_df = pd.DataFrame(list(nodes.values()))
    edges_df = pd.DataFrame(list(edges), columns=["source_id", "relation", "target_id"])
    
    # 保存到data目录
    output_dir = "data"
    os.makedirs(output_dir, exist_ok=True)
    nodes_path = os.path.join(output_dir, "nodes_vXXX.csv")
    edges_path = os.path.join(output_dir, "edges_vXXX.csv")
    
    nodes_df.to_csv(nodes_path, index=False, encoding='utf-8-sig')
    edges_df.to_csv(edges_path, index=False, encoding='utf-8-sig')

    print(f"\n--- 任务成功! ---")
    print(f"生成 '{nodes_path}' 文件，包含 {len(nodes)} 条记录。")
    print(f"生成 '{edges_path}' 文件，包含 {len(edges)} 条记录。")
    print(f"文件已保存在: {os.path.abspath(output_dir)}")

if __name__ == "__main__":
    main()