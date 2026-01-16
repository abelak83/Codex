import json
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd
import streamlit as st

ROOT = Path(__file__).parent
AI_TEMPLATE_PATH = ROOT / "config" / "ai_templates.json"
APPARATUS_PATH = ROOT / "config" / "connection_apparatus.json"

HV_TYPES = ["Линия", "Трансформатор", "ТН", "СВ", "СР"]
LV_TYPES = ["Линия", "ТСН", "ТН", "СВ", "Ввод", "СР"]

VOLTAGE_CLASSES = [6, 10, 35, 110, 220]


@dataclass
class Connection:
    name: str = ""
    voltage_class: int = 35
    connection_type: str = ""
    apparatus_counts: Dict[str, int] = field(default_factory=dict)


@dataclass
class Project:
    connections: List[Connection] = field(default_factory=list)


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_project(project: Project) -> str:
    payload = {
        "connections": [
            {
                "name": connection.name,
                "voltage_class": connection.voltage_class,
                "connection_type": connection.connection_type,
                "apparatus_counts": connection.apparatus_counts,
            }
            for connection in project.connections
        ]
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def load_project(data: str) -> Project:
    payload = json.loads(data)
    connections = []
    for item in payload.get("connections", []):
        connections.append(
            Connection(
                name=item.get("name", ""),
                voltage_class=int(item.get("voltage_class", 35)),
                connection_type=item.get("connection_type", ""),
                apparatus_counts=item.get("apparatus_counts", {}),
            )
        )
    return Project(connections=connections)


def voltage_group(voltage_class: int) -> str:
    return "hv" if voltage_class >= 35 else "lv"


def list_connection_types(voltage_class: int) -> List[str]:
    return HV_TYPES if voltage_class >= 35 else LV_TYPES


def format_apparatus_summary(apparatus_counts: Dict[str, int]) -> str:
    if not apparatus_counts:
        return "КА: нет"
    parts = []
    for name, count in apparatus_counts.items():
        if count > 0:
            parts.append(f"{name}×{count}")
    return "КА: нет" if not parts else "КА: " + ", ".join(parts)


def normalize_apparatus_counts(
    connection_type: str,
    voltage_class: int,
    apparatus_counts: Dict[str, int],
) -> Dict[str, int]:
    if connection_type not in {"СВ", "СР"}:
        return apparatus_counts
    if voltage_class < 35:
        return apparatus_counts
    sr_count = apparatus_counts.get("СР", 0)
    zn_per_sr = apparatus_counts.get("ЗН СР", 0)
    if sr_count == 0 or zn_per_sr == 0:
        return apparatus_counts
    normalized = dict(apparatus_counts)
    normalized["ЗН СР"] = sr_count * zn_per_sr
    return normalized


def apparatus_instances(apparatus_counts: Dict[str, int]) -> List[str]:
    instances: List[str] = []
    for name, count in apparatus_counts.items():
        if count <= 0:
            continue
        if count == 1:
            instances.append(name)
        else:
            for index in range(1, count + 1):
                instances.append(f"{name}-{index}")
    return instances


def signal_unit(signal_name: str) -> str:
    if signal_name.startswith("Ток"):
        return "А"
    if signal_name.startswith("Напряжение"):
        return "В"
    if signal_name.startswith("Активная мощность"):
        return "Вт"
    if signal_name.startswith("Реактивная мощность"):
        return "вар"
    if signal_name.startswith("Полная мощность"):
        return "ВА"
    if signal_name.startswith("Частота"):
        return "Гц"
    return ""


def signal_level(signal_name: str) -> str:
    if signal_name.startswith("Ток"):
        return "0-5"
    if signal_name.startswith("Напряжение"):
        return "0-100"
    if signal_name.startswith("Частота"):
        return "50"
    if "мощность" in signal_name:
        return "-"
    return ""


def signal_place(signal_name: str, connection: Connection) -> str:
    if signal_name.startswith("Ток"):
        return f"ТТ {connection.voltage_class} кВ"
    if connection.connection_type == "ТН":
        return f"ТН {connection.voltage_class} кВ"
    return ""


def ai_rows(connection: Connection, templates: Dict[str, List[str]]) -> List[Dict[str, str]]:
    rows = []
    signals = templates.get(connection.connection_type, [])
    for signal_name in signals:
        rows.append(
            {
                "Наименование присоединения": connection.name,
                "Наименование сигнала": signal_name,
                "Тип сигнала": "ТИТ",
                "Ед. измер.": signal_unit(signal_name),
                "Уровень сигнала": signal_level(signal_name),
                "Место съема сигнала": signal_place(signal_name, connection),
                "Устройство регистрации сигнала": "",
            }
        )
    return rows


def di_signals_for_apparatus(
    connection: Connection,
    apparatus_name: str,
) -> List[Tuple[str, str, str]]:
    if apparatus_name.startswith("ВЭ"):
        base = [
            ("Рабочее положение ВЭ", "ТС", apparatus_name),
            ("Контрольное положение ВЭ", "ТС", apparatus_name),
            ("Управление местное", "ТС", apparatus_name),
        ]
    else:
        base = [
            ("Включен", "ТС", apparatus_name),
            ("Отключен", "ТС", apparatus_name),
            ("Управление местное", "ТС", apparatus_name),
            ("Неисправность привода", "АПТС", apparatus_name),
        ]
    if connection.voltage_class < 35:
        base.append(("Неисправность РЗА", "АПТС", "РЗА"))
        if connection.connection_type != "ТН":
            base.append(("Аварийное отключение", "АПТС", apparatus_name))
        if connection.connection_type == "ТН":
            base.extend(
                [
                    ("АВ цепей ТН отключен", "АПТС", "РЗА"),
                    ("Земля в сети", "АПТС", "РЗА"),
                ]
            )
    return base


def di_do_place(connection: Connection, apparatus_name: str) -> str:
    if connection.voltage_class >= 35:
        return f"ОРУ-{connection.voltage_class} кВ. Привод {apparatus_name}"
    return f"РУ-{connection.voltage_class} кВ. Привод {apparatus_name}"


def di_rows(connection: Connection, apparatus_counts: Dict[str, int]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    apparatus_list = apparatus_instances(apparatus_counts)
    for apparatus_name in apparatus_list:
        for signal_name, signal_type, apparatus_label in di_signals_for_apparatus(
            connection,
            apparatus_name,
        ):
            rows.append(
                {
                    "Наименование присоединения": connection.name,
                    "Наименование аппарата": apparatus_label,
                    "Наименование сигнала": signal_name,
                    "Тип сигнала": signal_type,
                    "Хар-ка сигнала": "ЗСК =220 В" if connection.voltage_class >= 35 else "ЗСК =24 В",
                    "Место съема сигнала": di_do_place(connection, apparatus_label),
                    "Устройство регистрации сигнала": "",
                }
            )
    return rows


def do_rows(connection: Connection, apparatus_counts: Dict[str, int]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    apparatus_list = apparatus_instances(apparatus_counts)
    for apparatus_name in apparatus_list:
        if apparatus_name.startswith("ВЭ"):
            signal_names = ["Вкатить", "Выкатить"]
        else:
            signal_names = ["Включить", "Отключить"]
        for signal_name in signal_names:
            rows.append(
                {
                    "Наименование присоединения": connection.name,
                    "Наименование аппарата": apparatus_name,
                    "Наименование сигнала": signal_name,
                    "Тип сигнала": "ТУ",
                    "Хар-ка сигнала": "=ЗСК 220 В",
                    "Место получения сигнала": di_do_place(connection, apparatus_name),
                    "Устройство формирования сигнала": "",
                }
            )
    return rows


def validate_project(
    project: Project,
    ai_templates: Dict[str, List[str]],
    apparatus_config: Dict[str, Dict[str, Dict[str, Dict[str, int]]]],
    allow_empty: bool,
) -> Tuple[List[str], List[str]]:
    errors = []
    warnings = []
    for index, connection in enumerate(project.connections, start=1):
        if not connection.name.strip():
            errors.append(f"Присоединение #{index}: пустое наименование.")
        if not connection.connection_type:
            errors.append(f"Присоединение #{index}: не выбран тип присоединения.")
        if connection.connection_type and connection.connection_type not in ai_templates:
            message = f"Присоединение #{index}: нет шаблона AI для типа {connection.connection_type}."
            if allow_empty:
                warnings.append(message)
            else:
                errors.append(message)
        group = voltage_group(connection.voltage_class)
        if connection.connection_type and connection.connection_type not in apparatus_config.get(group, {}):
            message = f"Присоединение #{index}: нет шаблона КА для типа {connection.connection_type}."
            if allow_empty:
                warnings.append(message)
            else:
                errors.append(message)
    return errors, warnings


def export_excel(project: Project, ai_templates: Dict[str, List[str]]) -> bytes:
    ai_data = []
    di_data = []
    do_data = []
    for connection in project.connections:
        normalized_counts = normalize_apparatus_counts(
            connection.connection_type,
            connection.voltage_class,
            connection.apparatus_counts,
        )
        ai_data.extend(ai_rows(connection, ai_templates))
        di_data.extend(di_rows(connection, normalized_counts))
        do_data.extend(do_rows(connection, normalized_counts))

    ai_df = pd.DataFrame(ai_data)
    di_df = pd.DataFrame(di_data)
    do_df = pd.DataFrame(do_data)

    if not ai_df.empty:
        ai_df.insert(0, "№ п/п", range(1, len(ai_df) + 1))
    if not di_df.empty:
        di_df.insert(0, "№ п/п", range(1, len(di_df) + 1))
    if not do_df.empty:
        do_df.insert(0, "№ п/п", range(1, len(do_df) + 1))

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        ai_df.to_excel(writer, index=False, sheet_name="AI")
        di_df.to_excel(writer, index=False, sheet_name="DI")
        do_df.to_excel(writer, index=False, sheet_name="DO")
    buffer.seek(0)
    return buffer.read()


def calculate_signal_counts(
    project: Project,
    ai_templates: Dict[str, List[str]],
) -> Dict[str, int]:
    ai_total = 0
    di_total = 0
    do_total = 0
    for connection in project.connections:
        normalized_counts = normalize_apparatus_counts(
            connection.connection_type,
            connection.voltage_class,
            connection.apparatus_counts,
        )
        ai_total += len(ai_rows(connection, ai_templates))
        di_total += len(di_rows(connection, normalized_counts))
        do_total += len(do_rows(connection, normalized_counts))
    return {
        "AI": ai_total,
        "DI": di_total,
        "DO": do_total,
        "TOTAL": ai_total + di_total + do_total,
    }


def ensure_session_state() -> None:
    if "project" not in st.session_state:
        st.session_state.project = Project()


st.set_page_config(page_title="Перечень сигналов АСУ ТП", layout="wide")
ensure_session_state()

ai_templates = load_json(AI_TEMPLATE_PATH)
apparatus_config = load_json(APPARATUS_PATH)

st.title("Перечень сигналов АСУ ТП")
st.write(
    "Заполните список присоединений и параметры коммутационных аппаратов, затем выгрузите Excel-файл."
)

allow_empty = st.checkbox("Разрешить пустые шаблоны (предупреждение вместо ошибки)", value=False)

st.subheader("Сохранение проекта")
project_json = save_project(st.session_state.project)
st.download_button(
    "Сохранить проект",
    data=project_json,
    file_name="project.json",
    mime="application/json",
)

uploaded_file = st.file_uploader("Загрузить проект", type=["json"], accept_multiple_files=False)
if uploaded_file is not None:
    try:
        loaded_project = load_project(uploaded_file.read().decode("utf-8"))
        st.session_state.project = loaded_project
        st.success("Проект загружен.")
    except json.JSONDecodeError:
        st.error("Не удалось загрузить проект: некорректный JSON.")

st.subheader("Присоединения")
if st.button("Добавить присоединение"):
    st.session_state.project.connections.append(Connection())

for idx, connection in enumerate(st.session_state.project.connections):
    with st.expander(f"Присоединение {idx + 1}: {connection.name or 'без имени'}", expanded=True):
        cols = st.columns(3)
        with cols[0]:
            connection.name = st.text_input(
                "Наименование присоединения",
                value=connection.name,
                key=f"name_{idx}",
            )
        with cols[1]:
            connection.voltage_class = st.selectbox(
                "Класс напряжения, кВ",
                options=VOLTAGE_CLASSES,
                index=VOLTAGE_CLASSES.index(connection.voltage_class)
                if connection.voltage_class in VOLTAGE_CLASSES
                else 0,
                key=f"voltage_{idx}",
            )
        with cols[2]:
            types = list_connection_types(connection.voltage_class)
            connection.connection_type = st.selectbox(
                "Тип присоединения",
                options=[""] + types,
                index=(types.index(connection.connection_type) + 1)
                if connection.connection_type in types
                else 0,
                key=f"type_{idx}",
            )

        if connection.connection_type:
            group = voltage_group(connection.voltage_class)
            available = apparatus_config.get(group, {}).get(connection.connection_type, {})
            if available:
                st.markdown("**Коммутационные аппараты**")
                for apparatus_name, limits in available.items():
                    count = connection.apparatus_counts.get(apparatus_name, limits.get("min", 0))
                    connection.apparatus_counts[apparatus_name] = st.number_input(
                        apparatus_name,
                        min_value=limits.get("min", 0),
                        max_value=limits.get("max", 1),
                        value=count,
                        step=1,
                        key=f"{idx}_{apparatus_name}",
                    )
                if connection.connection_type in {"СВ", "СР"} and connection.voltage_class >= 35:
                    st.info(
                        "Для СР учитывайте пары: если выбран 2 СР и 2 ЗН, итог будет 4 ЗН."
                    )
            else:
                st.warning("Для выбранного типа нет шаблона КА.")

        if st.button("Удалить присоединение", key=f"delete_{idx}"):
            st.session_state.project.connections.pop(idx)
            st.experimental_rerun()

st.subheader("Проверки")
errors, warnings = validate_project(
    st.session_state.project,
    ai_templates,
    apparatus_config,
    allow_empty,
)
if errors:
    st.error("\n".join(errors))
if warnings:
    st.warning("\n".join(warnings))
if not errors and not warnings:
    st.success("Ошибок и предупреждений нет.")

st.subheader("Статистика сигналов")
counts = calculate_signal_counts(st.session_state.project, ai_templates)
metrics = st.columns(4)
metrics[0].metric("AI", counts["AI"])
metrics[1].metric("DI", counts["DI"])
metrics[2].metric("DO", counts["DO"])
metrics[3].metric("Итого", counts["TOTAL"])

st.subheader("Выгрузка")
if st.button("Сформировать Excel"):
    if errors:
        st.error("Исправьте ошибки перед выгрузкой.")
    else:
        excel_bytes = export_excel(st.session_state.project, ai_templates)
        st.download_button(
            "Скачать Excel",
            data=excel_bytes,
            file_name="signals.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
