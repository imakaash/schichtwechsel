from __future__ import annotations


def store_metrics(wh, model: str, rows: list[dict]) -> None:
    """Replace one model's rows in hris.model_metrics, keeping the other models'."""
    wh.con.execute(
        """
        CREATE TABLE IF NOT EXISTS hris.model_metrics (
            model VARCHAR, metric VARCHAR, value DOUBLE, test_period VARCHAR
        )
        """
    )
    wh.con.execute("DELETE FROM hris.model_metrics WHERE model LIKE ?", [f"{model}%"])
    wh.append("hris.model_metrics", rows)
