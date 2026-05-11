from pathlib import Path
import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


FEATURES = [
    "rsi",
    "macd_hist",
    "relative_volume",
    "volatility_relative",
    "price_vs_vwap",
    "ema_9_vs_21",
    "score",
]


class SignalClassifier:
    def __init__(self, model_path: str = "/app/data/signal_model.joblib"):
        self.model_path = Path(model_path)
        self.model = None
        self._load()

    def _load(self) -> None:
        if self.model_path.exists():
            self.model = joblib.load(self.model_path)

    def train(self, rows: list[dict]) -> dict:
        if len(rows) < 30:
            return {"trained": False, "reason": "São necessários pelo menos 30 trades fechados com features."}
        df = pd.DataFrame(rows).dropna(subset=FEATURES + ["success"])
        if df.empty or df["success"].nunique() < 2:
            return {"trained": False, "reason": "Dados insuficientes ou sem classes distintas."}
        pipeline = Pipeline([("scaler", StandardScaler()), ("model", RandomForestClassifier(n_estimators=120, random_state=42))])
        pipeline.fit(df[FEATURES], df["success"].astype(int))
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(pipeline, self.model_path)
        self.model = pipeline
        return {"trained": True, "rows": len(df)}

    def predict_probability(self, features: dict) -> float | None:
        if self.model is None:
            return None
        row = pd.DataFrame([{name: features.get(name, 0) for name in FEATURES}])
        probability = self.model.predict_proba(row)[0][1]
        return round(float(probability), 4)
