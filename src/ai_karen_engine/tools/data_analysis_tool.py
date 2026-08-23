"""
Data Analysis Tool for AI-Karen
Statistical analysis and data processing capabilities.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Union
import statistics
from collections import Counter
from datetime import datetime
import json

from ai_karen_engine.services.tooling.tool_service import BaseTool, ToolMetadata, ToolCategory, ToolParameter

logger = logging.getLogger(__name__)


class DataAnalysisTool(BaseTool):
    """
    Production-grade data analysis tool.

    Features:
    - Statistical analysis (mean, median, mode, stdev, etc.)
    - Data aggregation and grouping
    - Data filtering and transformation
    - Time series analysis
    - Data validation and quality checks
    - JSON/CSV/dict data processing
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__()
        self.config = config or {}
        self.max_dataset_size = self.config.get('max_dataset_size', 1_000_000)

    def _create_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="data_analysis",
            description="Analyze data with statistical methods (statistics, aggregation, filtering, correlation)",
            category=ToolCategory.ANALYTICS,
            version="1.0.0",
            author="AI Karen",
            parameters=[
                ToolParameter(
                    name="operation",
                    type=str,
                    description="Operation to perform (statistics, count_values, filter, group_by, aggregate, sort, correlation, outliers, normalize)",
                    required=True
                ),
                ToolParameter(
                    name="data",
                    type=list,
                    description="Input data (list of numbers or dictionaries)",
                    required=True
                ),
                ToolParameter(
                    name="key",
                    type=str,
                    description="Key for grouping/sorting",
                    required=False
                ),
                ToolParameter(
                    name="filters",
                    type=dict,
                    description="Filters for data (field: value pairs)",
                    required=False
                ),
                ToolParameter(
                    name="aggregations",
                    type=dict,
                    description="Aggregations to perform (field: operation pairs)",
                    required=False
                ),
                ToolParameter(
                    name="method",
                    type=str,
                    description="Method for operation (e.g., 'iqr' for outliers)",
                    required=False
                )
            ],
            return_type=dict,
            examples=[
                {
                    "description": "Calculate statistics",
                    "parameters": {
                        "operation": "statistics",
                        "data": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
                    }
                },
                {
                    "description": "Group and aggregate data",
                    "parameters": {
                        "operation": "aggregate",
                        "data": [
                            {"category": "A", "value": 10},
                            {"category": "A", "value": 20},
                            {"category": "B", "value": 15}
                        ],
                        "key": "category",
                        "aggregations": {"value": "sum"}
                    }
                }
            ],
            tags=["data", "statistics", "analysis", "aggregation"],
            timeout=30
        )

    async def _execute(self, parameters: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Any:
        operation = parameters["operation"]
        data = parameters["data"]

        if operation == "statistics":
            return await self.calculate_statistics(data)

        elif operation == "count_values":
            top_n = parameters.get("top_n")
            return await self.count_values(data, top_n=top_n)

        elif operation == "filter":
            filters = parameters.get("filters", {})
            return await self.filter_data(data, filters)

        elif operation == "group_by":
            key = parameters["key"]
            return await self.group_by(data, key)

        elif operation == "aggregate":
            group_by = parameters["key"]
            aggregations = parameters["aggregations"]
            return await self.aggregate(data, group_by, aggregations)

        elif operation == "sort":
            key = parameters["key"]
            reverse = parameters.get("reverse", False)
            return await self.sort_data(data, key, reverse=reverse)

        elif operation == "correlation":
            if len(data) != 2:
                raise ValueError("Correlation requires exactly 2 lists of values")
            return await self.calculate_correlation(data[0], data[1])

        elif operation == "outliers":
            method = parameters.get("method", "iqr")
            threshold = parameters.get("threshold", 1.5)
            return await self.detect_outliers(data, method=method, threshold=threshold)

        elif operation == "normalize":
            method = parameters.get("method", "minmax")
            return await self.normalize_data(data, method=method)

        else:
            raise ValueError(f"Unknown operation: {operation}")

    async def calculate_statistics(
        self,
        data: List[Union[int, float]]
    ) -> Dict[str, Any]:
        if not data:
            raise ValueError("Empty dataset")

        if len(data) > self.max_dataset_size:
            raise ValueError(f"Dataset too large: {len(data)} (max: {self.max_dataset_size})")

        numeric_data = [x for x in data if isinstance(x, (int, float))]

        if not numeric_data:
            raise ValueError("No numeric values in dataset")

        result = {
            'count': len(numeric_data),
            'sum': sum(numeric_data),
            'mean': statistics.mean(numeric_data),
            'median': statistics.median(numeric_data),
            'min': min(numeric_data),
            'max': max(numeric_data),
            'range': max(numeric_data) - min(numeric_data)
        }

        try:
            result['mode'] = statistics.mode(numeric_data)
        except statistics.StatisticsError:
            result['mode'] = None

        if len(numeric_data) >= 2:
            result['stdev'] = statistics.stdev(numeric_data)
            result['variance'] = statistics.variance(numeric_data)
        else:
            result['stdev'] = None
            result['variance'] = None

        result['q1'] = statistics.quantiles(numeric_data, n=4)[0]
        result['q2'] = statistics.quantiles(numeric_data, n=4)[1]
        result['q3'] = statistics.quantiles(numeric_data, n=4)[2]

        return result

    async def count_values(
        self,
        data: List[Any],
        top_n: Optional[int] = None
    ) -> Dict[Any, int]:
        counter = Counter(data)

        if top_n:
            return dict(counter.most_common(top_n))
        return dict(counter)

    async def filter_data(
        self,
        data: List[Dict[str, Any]],
        filters: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        result = []

        for item in data:
            match = True
            for key, value in filters.items():
                if key not in item or item[key] != value:
                    match = False
                    break
            if match:
                result.append(item)

        return result

    async def group_by(
        self,
        data: List[Dict[str, Any]],
        key: str
    ) -> Dict[Any, List[Dict[str, Any]]]:
        groups = {}

        for item in data:
            if key not in item:
                continue

            group_key = item[key]
            if group_key not in groups:
                groups[group_key] = []
            groups[group_key].append(item)

        return groups

    async def aggregate(
        self,
        data: List[Dict[str, Any]],
        group_by: str,
        aggregations: Dict[str, str]
    ) -> List[Dict[str, Any]]:
        groups = await self.group_by(data, group_by)
        results = []

        for group_key, items in groups.items():
            result = {group_by: group_key}

            for field, operation in aggregations.items():
                values = [item.get(field) for item in items if field in item]
                numeric_values = [v for v in values if isinstance(v, (int, float))]

                if operation == 'sum':
                    result[f'{field}_sum'] = sum(numeric_values) if numeric_values else 0
                elif operation == 'avg':
                    result[f'{field}_avg'] = (
                        statistics.mean(numeric_values) if numeric_values else None
                    )
                elif operation == 'count':
                    result[f'{field}_count'] = len(values)
                elif operation == 'min':
                    result[f'{field}_min'] = min(numeric_values) if numeric_values else None
                elif operation == 'max':
                    result[f'{field}_max'] = max(numeric_values) if numeric_values else None

            results.append(result)

        return results

    async def sort_data(
        self,
        data: List[Dict[str, Any]],
        key: str,
        reverse: bool = False
    ) -> List[Dict[str, Any]]:
        return sorted(data, key=lambda x: x.get(key, 0), reverse=reverse)

    async def pivot_table(
        self,
        data: List[Dict[str, Any]],
        rows: str,
        columns: str,
        values: str,
        aggfunc: str = 'sum'
    ) -> Dict[str, Any]:
        pivot = {}

        for item in data:
            if rows not in item or columns not in item or values not in item:
                continue

            row_key = item[rows]
            col_key = item[columns]
            value = item[values]

            if row_key not in pivot:
                pivot[row_key] = {}

            if col_key not in pivot[row_key]:
                pivot[row_key][col_key] = []

            pivot[row_key][col_key].append(value)

        result = {}
        for row_key, row_data in pivot.items():
            result[row_key] = {}
            for col_key, values in row_data.items():
                numeric_values = [v for v in values if isinstance(v, (int, float))]

                if aggfunc == 'sum':
                    result[row_key][col_key] = sum(numeric_values)
                elif aggfunc == 'avg':
                    result[row_key][col_key] = (
                        statistics.mean(numeric_values) if numeric_values else None
                    )
                elif aggfunc == 'count':
                    result[row_key][col_key] = len(values)
                elif aggfunc == 'min':
                    result[row_key][col_key] = min(numeric_values) if numeric_values else None
                elif aggfunc == 'max':
                    result[row_key][col_key] = max(numeric_values) if numeric_values else None

        return result

    async def detect_outliers(
        self,
        data: List[Union[int, float]],
        method: str = 'iqr',
        threshold: float = 1.5
    ) -> Dict[str, Any]:
        numeric_data = [x for x in data if isinstance(x, (int, float))]

        if len(numeric_data) < 4:
            return {'outliers': [], 'outlier_indices': [], 'method': method}

        outliers = []
        outlier_indices = []

        if method == 'iqr':
            q1 = statistics.quantiles(numeric_data, n=4)[0]
            q3 = statistics.quantiles(numeric_data, n=4)[2]
            iqr = q3 - q1
            lower_bound = q1 - threshold * iqr
            upper_bound = q3 + threshold * iqr

            for i, value in enumerate(numeric_data):
                if value < lower_bound or value > upper_bound:
                    outliers.append(value)
                    outlier_indices.append(i)

        elif method == 'zscore':
            mean = statistics.mean(numeric_data)
            stdev = statistics.stdev(numeric_data)

            for i, value in enumerate(numeric_data):
                z_score = abs((value - mean) / stdev) if stdev > 0 else 0
                if z_score > threshold:
                    outliers.append(value)
                    outlier_indices.append(i)

        return {
            'outliers': outliers,
            'outlier_indices': outlier_indices,
            'outlier_count': len(outliers),
            'method': method,
            'threshold': threshold
        }

    async def normalize_data(
        self,
        data: List[Union[int, float]],
        method: str = 'minmax',
        range_min: float = 0.0,
        range_max: float = 1.0
    ) -> List[float]:
        numeric_data = [x for x in data if isinstance(x, (int, float))]

        if not numeric_data:
            return []

        if method == 'minmax':
            min_val = min(numeric_data)
            max_val = max(numeric_data)
            range_val = max_val - min_val

            if range_val == 0:
                return [range_min] * len(numeric_data)

            return [
                range_min + (x - min_val) * (range_max - range_min) / range_val
                for x in numeric_data
            ]

        elif method == 'zscore':
            mean = statistics.mean(numeric_data)
            stdev = statistics.stdev(numeric_data) if len(numeric_data) >= 2 else 1

            if stdev == 0:
                return [0.0] * len(numeric_data)

            return [(x - mean) / stdev for x in numeric_data]

        else:
            raise ValueError(f"Unknown normalization method: {method}")

    async def calculate_correlation(
        self,
        x: List[Union[int, float]],
        y: List[Union[int, float]]
    ) -> float:
        if len(x) != len(y):
            raise ValueError("Datasets must have same length")

        if len(x) < 2:
            raise ValueError("Need at least 2 data points")

        pairs = [(xi, yi) for xi, yi in zip(x, y)
                 if isinstance(xi, (int, float)) and isinstance(yi, (int, float))]

        if len(pairs) < 2:
            raise ValueError("Need at least 2 numeric pairs")

        x_vals = [p[0] for p in pairs]
        y_vals = [p[1] for p in pairs]

        return statistics.correlation(x_vals, y_vals)

    async def validate_data_quality(
        self,
        data: List[Dict[str, Any]],
        required_fields: List[str],
        field_types: Optional[Dict[str, type]] = None
    ) -> Dict[str, Any]:
        field_types = field_types or {}

        total_records = len(data)
        valid_records = 0
        missing_fields = {field: 0 for field in required_fields}
        type_errors = {field: 0 for field in field_types}
        null_values = {}

        for item in data:
            record_valid = True

            for field in required_fields:
                if field not in item or item[field] is None:
                    missing_fields[field] += 1
                    record_valid = False

            for field, expected_type in field_types.items():
                if field in item and item[field] is not None:
                    if not isinstance(item[field], expected_type):
                        type_errors[field] += 1
                        record_valid = False

            for key, value in item.items():
                if value is None:
                    null_values[key] = null_values.get(key, 0) + 1

            if record_valid:
                valid_records += 1

        return {
            'total_records': total_records,
            'valid_records': valid_records,
            'invalid_records': total_records - valid_records,
            'validity_rate': valid_records / total_records if total_records > 0 else 0,
            'missing_fields': missing_fields,
            'type_errors': type_errors,
            'null_values': null_values
        }


_data_analysis_tool_instance = None


def get_data_analysis_tool(
    config: Optional[Dict[str, Any]] = None
) -> DataAnalysisTool:
    global _data_analysis_tool_instance
    if _data_analysis_tool_instance is None:
        _data_analysis_tool_instance = DataAnalysisTool(config)
    return _data_analysis_tool_instance
