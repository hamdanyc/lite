import os
import textwrap
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

# --- Configuration ---
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CODEBOOK_PATH = BASE_DIR / "output" / "codebook.csv"
DEFAULT_ANALYSIS_PATH = BASE_DIR / "output" / "qualitative_analysis_granular.csv"
DEFAULT_FILEID_PATH = BASE_DIR / "output" / "fileid.csv"
DEFAULT_OUTPUT_DIR = BASE_DIR / "chart"
DEFAULT_OUTPUT_PLOT_FILE = DEFAULT_OUTPUT_DIR / "plot.png"


def _resolve_path(path_value, default_path):
    if path_value is None:
        return Path(default_path)
    path = Path(path_value)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def _find_factor_column(columns):
    names = {str(col).strip().lower(): col for col in columns}
    for preferred in ("main factor", "main_factor", "factor"):
        if preferred in names:
            return names[preferred]
    raise KeyError(
        "Could not find a factor column. Expected one of: 'main factor', 'main_factor', or 'factor'."
    )


def _resolve_grouping_columns(df_codebook, group_by):
    aliases = {
        "main factor": ("main factor", "main factor name"),
        "main_factor": ("main factor", "main factor name"),
        "mainfactor": ("main factor", "main factor name"),
        "sub factor": ("sub factor", "sub factor name"),
        "sub_factor": ("sub factor", "sub factor name"),
        "subfactor": ("sub factor", "sub factor name"),
    }

    normalized = str(group_by).strip().lower()
    if normalized not in aliases:
        raise KeyError(f"Unsupported group_by '{group_by}'. Expected 'main factor' or 'sub factor'.")

    data_col, label_col = aliases[normalized]
    if data_col not in df_codebook.columns:
        raise KeyError(f"Could not find '{data_col}' in the codebook CSV.")

    return data_col, label_col


def build_factor_stats(
    codebook_path,
    analysis_path,
    group_by="main factor",
    fileid_path=None,
    by_gender=False,
    by_attribute=None,
):
    """Aggregate occurrence counts for either the main factor or sub factor hierarchy."""
    codebook_path = _resolve_path(codebook_path, DEFAULT_CODEBOOK_PATH)
    analysis_path = _resolve_path(analysis_path, DEFAULT_ANALYSIS_PATH)
    fileid_path = _resolve_path(fileid_path, DEFAULT_FILEID_PATH) if fileid_path else None

    df_codebook = pd.read_csv(codebook_path)
    df_analysis = pd.read_csv(analysis_path)

    split_by = by_attribute or ("gender" if by_gender else None)
    if fileid_path and fileid_path.exists():
        df_fileid = pd.read_csv(fileid_path)
        if split_by is None and {"file-id", "gender"}.issubset(df_fileid.columns):
            split_by = "gender"
        if split_by:
            if "file-id" not in df_fileid.columns or split_by not in df_fileid.columns:
                raise KeyError(f"Could not find '{split_by}' metadata in fileid.csv.")
            df_analysis = df_analysis.merge(
                df_fileid[["file-id", split_by]],
                on="file-id",
                how="left",
            )
    if split_by and split_by not in df_analysis.columns:
        raise KeyError(f"{split_by.title()} analysis requested, but no '{split_by}' data is available.")

    group_column = _find_factor_column(df_analysis.columns)
    if str(group_by).strip().lower() in {"sub factor", "sub_factor", "subfactor"}:
        group_column = "sub factor"
    elif str(group_by).strip().lower() in {"main factor", "main_factor", "mainfactor"}:
        group_column = _find_factor_column(df_analysis.columns)
    else:
        raise KeyError(f"Unsupported group_by '{group_by}'. Expected 'main factor' or 'sub factor'.")

    df_analysis = df_analysis[df_analysis[group_column].notna()]
    df_analysis = df_analysis[
        df_analysis[group_column].map(lambda value: str(value).strip() != "")
    ]

    if split_by:
        df_analysis[split_by] = df_analysis[split_by].astype("object").fillna("Unknown")
        stats = (
            df_analysis.groupby([group_column, split_by], dropna=False)
            .size()
            .rename("Count")
            .reset_index()
            .rename(columns={group_column: group_by})
        )
        if split_by == "gender":
            gender_rank = {"m": 0, "male": 0, "f": 1, "female": 1, "unknown": 2, "other": 3}
            stats["_attribute_order"] = stats[split_by].astype(str).str.lower().map(
                lambda value: gender_rank.get(value, 99)
            )
            stats = stats.sort_values([group_by, "_attribute_order"]).drop(columns="_attribute_order")
        else:
            stats = stats.sort_values([group_by, split_by], key=lambda values: values.astype(str))
    else:
        stats = (
            df_analysis.groupby(group_column)
            .size()
            .rename("Count")
            .reset_index()
            .rename(columns={group_column: group_by})
        )

    data_col, label_col = _resolve_grouping_columns(df_codebook, group_by)
    if label_col in df_codebook.columns:
        codebook_labels = (
            df_codebook[[data_col, label_col]]
            .drop_duplicates()
            .rename(columns={data_col: group_by, label_col: label_col})
        )
        stats = stats.merge(codebook_labels, on=group_by, how="left")

    return stats


def analyze_and_visualize_data(
    codebook_path,
    analysis_path,
    output_dir=None,
    group_by="main factor",
    output_file="plot.png",
    by_gender=False,
    fileid_path=None,
    by_attribute=None,
):
    """
    Reads two CSV files, calculates descriptive statistics for a factor hierarchy,
    and saves a bar chart for that grouping level.
    """
    codebook_path = _resolve_path(codebook_path, DEFAULT_CODEBOOK_PATH)
    analysis_path = _resolve_path(analysis_path, DEFAULT_ANALYSIS_PATH)
    fileid_path = _resolve_path(fileid_path, DEFAULT_FILEID_PATH) if fileid_path else None
    output_dir = _resolve_path(output_dir, DEFAULT_OUTPUT_DIR) if output_dir else DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    output_plot_file = output_dir / output_file

    try:
        print(f"Reading data from {codebook_path} and {analysis_path}...")
        stats = build_factor_stats(
            codebook_path,
            analysis_path,
            group_by=group_by,
            fileid_path=fileid_path,
            by_gender=by_gender,
            by_attribute=by_attribute,
        )
    except FileNotFoundError as e:
        print(f"ERROR: One of the files was not found. Please ensure '{e.filename}' exists.")
        return None
    except Exception as e:
        print(f"An error occurred during analysis: {e}")
        return None

    title_text = "Distribution of Qualitative Responses by Main Factor"
    x_axis_label = "Main factor"
    label_key = "main factor name"
    if str(group_by).strip().lower() in {"sub factor", "sub_factor", "subfactor"}:
        title_text = "Distribution of Qualitative Responses by Sub Factor"
        x_axis_label = "Sub factor"
        label_key = "sub factor name"

    split_by = by_attribute or ("gender" if by_gender else None)
    if split_by:
        title_text = f"{title_text} by {split_by.replace('-', ' ').title()}"

    print("\n" + "=" * 50)
    print(f"DESCRIPTIVE STATISTICS BY {x_axis_label.upper()}{f' AND {split_by.upper()}' if split_by else ''}")
    print("=" * 50)
    print(stats.to_string(index=False))
    print("\n" + "=" * 50)

    print("\n" + "=" * 50)
    print("DRAWING FACTOR COUNTS")
    print("=" * 50)

    is_sub_factor = str(group_by).strip().lower() in {"sub factor", "sub_factor", "subfactor"}
    figure_size = (14, 6) if is_sub_factor else ((14, 7) if split_by else (12, 6))
    fig, ax = plt.subplots(figsize=figure_size)
    if stats.empty:
        ax.text(0.5, 0.5, "No factor data available", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        fig.suptitle(title_text, fontsize=18, y=1.02)
    elif split_by:
        gender_rank = {"m": 0, "male": 0, "f": 1, "female": 1, "unknown": 2, "other": 3}
        attribute_order = sorted(
            stats[split_by].dropna().unique().tolist(),
            key=lambda value: gender_rank.get(str(value).lower(), 99)
            if split_by == "gender"
            else str(value),
        )
        pivot = stats.pivot(index=group_by, columns=split_by, values="Count").fillna(0).astype(int)
        pivot = pivot.reindex(sorted(pivot.index.tolist(), key=lambda value: str(value)))
        factor_names = stats.drop_duplicates(subset=[group_by]).set_index(group_by)[label_key]
        x_positions = range(len(pivot))
        bar_width = 0.8 / max(1, len(attribute_order))
        labels = []
        for factor in pivot.index:
            label_value = factor_names.get(factor)
            if pd.isna(label_value):
                label_value = f"Factor {factor}"
            label = str(label_value)
            label = label.replace("PILLAR", "P")
            label = label.replace(" & ", " & ")
            label = " ".join(label.split())
            if is_sub_factor:
                labels.append(f"{factor}\n{label[:28]}")
            else:
                if label.startswith("P ") and ":" in label:
                    label = label.partition(":")[2].strip()
                labels.append(textwrap.fill(label, width=22))

        for idx, attribute_value in enumerate(attribute_order):
            offset = idx * bar_width - (len(attribute_order) - 1) * bar_width / 2
            values = pivot[attribute_value].tolist()
            ax.bar(
                [pos + offset for pos in x_positions],
                values,
                width=bar_width,
                label=str(attribute_value),
                alpha=0.8,
            )

        ax.set_title(title_text, fontsize=18, pad=20)
        ax.set_xlabel(x_axis_label)
        ax.set_ylabel("Number of responses")
        ax.set_xticks(list(x_positions))
        if is_sub_factor:
            ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
        else:
            ax.set_xticklabels(labels, rotation=0, fontsize=9)
        ax.grid(axis="y", linestyle="--", alpha=0.4)
        ax.legend(title=split_by.replace("-", " ").title())

        for container in ax.containers:
            for bar in container:
                height = bar.get_height()
                if height > 0:
                    ax.text(
                        bar.get_x() + bar.get_width() / 2,
                        height + 0.2,
                        str(int(height)),
                        ha="center",
                        va="bottom",
                        fontsize=8,
                    )
    else:
        ordered = stats.sort_values("Count", ascending=False).reset_index(drop=True)
        factors = ordered[group_by].astype(str).tolist()
        factor_labels = []
        for _, row in ordered.iterrows():
            factor = row[group_by]
            label_value = row.get(label_key)
            if pd.isna(label_value):
                label_value = f"Factor {factor}"
            factor_labels.append(label_value)
        counts = ordered["Count"].astype(int).tolist()
        colors = sns.color_palette("Set2", n_colors=len(ordered))

        x_positions = range(len(factors))
        bars = ax.bar(x_positions, counts, color=colors, edgecolor="black", width=0.8)
        ax.set_title(title_text, fontsize=18, pad=20)
        ax.set_xlabel(x_axis_label)
        ax.set_ylabel("Number of responses")
        ax.set_xticks(list(x_positions))

        formatted_labels = []
        for factor, name in zip(factors, factor_labels):
            label = str(name)
            label = label.replace("PILLAR", "P")
            label = label.replace(" & ", " & ")
            label = label.replace("Maslovian", "Maslow")
            label = label.replace("Metacognitive", "Meta")
            label = label.replace("Technostress", "Tech stress")
            label = label.replace("Cognitive", "Cog")
            label = label.replace("Self-Directed", "Self-dir")
            label = label.replace("Uncertainty", "Uncertainty")
            label = label.replace("Scaffolding", "Scaffold")
            label = label.replace("AI-Coached", "AI coach")
            cleaned = " ".join(label.split())
            short = cleaned[:28]
            if len(cleaned) > 28:
                short = short.rstrip() + "..."
            formatted_labels.append(f"{factor}\n{short}")
        if is_sub_factor:
            ax.set_xticklabels(formatted_labels, rotation=45, ha="right", fontsize=8)
        else:
            ax.set_xticklabels(formatted_labels, rotation=0, fontsize=9)
        ax.grid(axis="y", linestyle="--", alpha=0.4)

        for bar, count in zip(bars, counts):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                count + 0.5,
                str(count),
                ha="center",
                va="bottom",
                fontsize=9,
            )

    try:
        plt.tight_layout()
        plt.savefig(output_plot_file, bbox_inches="tight")
        print(f"\nSUCCESS: Plot saved successfully to '{output_plot_file}'")
        return output_plot_file
    except Exception as e:
        print(f"\nERROR: Failed to save the plot file: {e}")
        return None
    finally:
        plt.close(fig)


# --- Execution ---
if __name__ == "__main__":
    analyze_and_visualize_data(
        DEFAULT_CODEBOOK_PATH,
        DEFAULT_ANALYSIS_PATH,
        output_dir=DEFAULT_OUTPUT_DIR,
        output_file="plot.png",
    )
    analyze_and_visualize_data(
        DEFAULT_CODEBOOK_PATH,
        DEFAULT_ANALYSIS_PATH,
        output_dir=DEFAULT_OUTPUT_DIR,
        group_by="sub factor",
        output_file="sub_factor_plot.png",
    )
    analyze_and_visualize_data(
        DEFAULT_CODEBOOK_PATH,
        DEFAULT_ANALYSIS_PATH,
        output_dir=DEFAULT_OUTPUT_DIR,
        group_by="main factor",
        output_file="main_factor_by_gender_plot.png",
        by_gender=True,
        fileid_path=DEFAULT_FILEID_PATH,
    )
    analyze_and_visualize_data(
        DEFAULT_CODEBOOK_PATH,
        DEFAULT_ANALYSIS_PATH,
        output_dir=DEFAULT_OUTPUT_DIR,
        group_by="main factor",
        output_file="main_factor_by_age_group_plot.png",
        fileid_path=DEFAULT_FILEID_PATH,
        by_attribute="age-group",
    )
    analyze_and_visualize_data(
        DEFAULT_CODEBOOK_PATH,
        DEFAULT_ANALYSIS_PATH,
        output_dir=DEFAULT_OUTPUT_DIR,
        group_by="main factor",
        output_file="main_factor_by_status_plot.png",
        fileid_path=DEFAULT_FILEID_PATH,
        by_attribute="status",
    )
    analyze_and_visualize_data(
        DEFAULT_CODEBOOK_PATH,
        DEFAULT_ANALYSIS_PATH,
        output_dir=DEFAULT_OUTPUT_DIR,
        group_by="sub factor",
        output_file="sub_factor_by_age_group_plot.png",
        fileid_path=DEFAULT_FILEID_PATH,
        by_attribute="age-group",
    )
    analyze_and_visualize_data(
        DEFAULT_CODEBOOK_PATH,
        DEFAULT_ANALYSIS_PATH,
        output_dir=DEFAULT_OUTPUT_DIR,
        group_by="sub factor",
        output_file="sub_factor_by_status_plot.png",
        fileid_path=DEFAULT_FILEID_PATH,
        by_attribute="status",
    )
    analyze_and_visualize_data(
        DEFAULT_CODEBOOK_PATH,
        DEFAULT_ANALYSIS_PATH,
        output_dir=DEFAULT_OUTPUT_DIR,
        group_by="sub factor",
        output_file="sub_factor_by_gender_plot.png",
        by_gender=True,
        fileid_path=DEFAULT_FILEID_PATH,
    )
