"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-01-01
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables() -> set[str]:
    bind = op.get_bind()
    return set(sa.inspect(bind).get_table_names())


def _existing_indexes(table_name: str) -> set[str]:
    bind = op.get_bind()
    return {ix["name"] for ix in sa.inspect(bind).get_indexes(table_name) if ix.get("name")}


def _create_index_if_missing(name: str, table: str, cols: list[str], unique: bool = False) -> None:
    if name not in _existing_indexes(table):
        op.create_index(name, table, cols, unique=unique)


def upgrade() -> None:
    existing = _existing_tables()

    if "app_config" not in existing:
        op.create_table(
            "app_config",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("environment", sa.String(20), nullable=False),
            sa.Column("trigger_percentage", sa.Numeric(10, 4), nullable=False),
            sa.Column("trigger_window_seconds", sa.Integer(), nullable=False),
            sa.Column("base_margin", sa.Numeric(20, 8), nullable=False),
            sa.Column("leverage", sa.Integer(), nullable=False),
            sa.Column("max_concurrent_trades", sa.Integer(), nullable=False),
            sa.Column("profit_reinvestment_pct", sa.Numeric(10, 4), nullable=False),
            sa.Column("max_trade_allocation", sa.Numeric(20, 8), nullable=False),
            sa.Column("daily_loss_limit", sa.Numeric(20, 8), nullable=False),
            sa.Column("max_drawdown_pct", sa.Numeric(10, 4), nullable=False),
            sa.Column("max_aggregate_exposure", sa.Numeric(20, 8), nullable=False),
            sa.Column("max_consecutive_losses", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("max_slippage_bps", sa.Numeric(10, 4), nullable=False),
            sa.Column("taker_fee_bps", sa.Numeric(10, 4), nullable=False),
            sa.Column("candidate_ttl_seconds", sa.Integer(), nullable=False),
            sa.Column("cooldown_seconds", sa.Integer(), nullable=False),
            sa.Column("protection_deadline_seconds", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )

    if "exchange_credentials" not in existing:
        op.create_table(
            "exchange_credentials",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("exchange", sa.String(50), nullable=False),
            sa.Column("environment", sa.String(20), nullable=False),
            sa.Column("api_key_ciphertext", sa.Text(), nullable=False),
            sa.Column("api_secret_ciphertext", sa.Text(), nullable=False),
            sa.Column("encryption_key_version", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        )

    if "signal_candidates" not in existing:
        op.create_table(
            "signal_candidates",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("event_key", sa.String(200), nullable=False, unique=True),
            sa.Column("symbol", sa.String(20), nullable=False),
            sa.Column("direction", sa.String(10), nullable=False),
            sa.Column("current_price", sa.Numeric(20, 8), nullable=False),
            sa.Column("reference_price", sa.Numeric(20, 8), nullable=False),
            sa.Column("change_pct", sa.Numeric(20, 8), nullable=False),
            sa.Column("window_seconds", sa.Integer(), nullable=False),
            sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("exchange_event_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("rejection_reason", sa.Text(), nullable=True),
            sa.Column("snapshot_json", sa.Text(), nullable=True),
        )
    _create_index_if_missing("ix_signal_candidates_event_key", "signal_candidates", ["event_key"], unique=True)
    _create_index_if_missing("ix_signal_candidates_symbol", "signal_candidates", ["symbol"])
    _create_index_if_missing("ix_signal_candidates_detected_at", "signal_candidates", ["detected_at"])
    _create_index_if_missing("ix_signal_candidates_status", "signal_candidates", ["status"])

    if "trades" not in existing:
        op.create_table(
            "trades",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("candidate_id", sa.String(36), sa.ForeignKey("signal_candidates.id"), nullable=True),
            sa.Column("symbol", sa.String(20), nullable=False),
            sa.Column("side", sa.String(10), nullable=False),
            sa.Column("direction", sa.String(10), nullable=False),
            sa.Column("entry_order_client_id", sa.String(64), nullable=False, unique=True),
            sa.Column("entry_order_id", sa.String(64), nullable=True),
            sa.Column("entry_price", sa.Numeric(20, 8), nullable=True),
            sa.Column("exit_price", sa.Numeric(20, 8), nullable=True),
            sa.Column("position_size", sa.Numeric(20, 8), nullable=True),
            sa.Column("notional", sa.Numeric(20, 8), nullable=True),
            sa.Column("margin_allocation", sa.Numeric(20, 8), nullable=False),
            sa.Column("leverage", sa.Integer(), nullable=False),
            sa.Column("take_profit", sa.Numeric(20, 8), nullable=True),
            sa.Column("stop_loss", sa.Numeric(20, 8), nullable=True),
            sa.Column("modeled_max_loss", sa.Numeric(20, 8), nullable=True),
            sa.Column("realized_pnl", sa.Numeric(20, 8), nullable=True),
            sa.Column("fees", sa.Numeric(20, 8), nullable=True),
            sa.Column("funding", sa.Numeric(20, 8), nullable=True),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("close_reason", sa.String(50), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        )
    _create_index_if_missing("ix_trades_symbol", "trades", ["symbol"])
    _create_index_if_missing("ix_trades_status", "trades", ["status"])
    _create_index_if_missing("ix_trades_created_at", "trades", ["created_at"])
    _create_index_if_missing("ix_trades_status_created", "trades", ["status", "created_at"])
    _create_index_if_missing("ix_trades_symbol_created", "trades", ["symbol", "created_at"])

    if "orders" not in existing:
        op.create_table(
            "orders",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("trade_id", sa.String(36), sa.ForeignKey("trades.id"), nullable=True),
            sa.Column("client_order_id", sa.String(64), nullable=False, unique=True),
            sa.Column("exchange_order_id", sa.String(64), nullable=True),
            sa.Column("symbol", sa.String(20), nullable=False),
            sa.Column("order_type", sa.String(30), nullable=False),
            sa.Column("side", sa.String(10), nullable=False),
            sa.Column("reduce_only", sa.Boolean(), nullable=False),
            sa.Column("quantity", sa.Numeric(20, 8), nullable=False),
            sa.Column("price", sa.Numeric(20, 8), nullable=True),
            sa.Column("trigger_price", sa.Numeric(20, 8), nullable=True),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    _create_index_if_missing("ix_orders_trade_id", "orders", ["trade_id"])
    _create_index_if_missing("ix_orders_client_order_id", "orders", ["client_order_id"], unique=True)

    if "agent_logs" not in existing:
        op.create_table(
            "agent_logs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("candidate_id", sa.String(36), sa.ForeignKey("signal_candidates.id"), nullable=True),
            sa.Column("trade_id", sa.String(36), nullable=True),
            sa.Column("agent_name", sa.String(50), nullable=False),
            sa.Column("provider", sa.String(50), nullable=False),
            sa.Column("model_or_agent_id", sa.String(100), nullable=True),
            sa.Column("prompt_version", sa.String(50), nullable=True),
            sa.Column("schema_version", sa.String(20), nullable=False),
            sa.Column("request_hash", sa.String(100), nullable=True),
            sa.Column("response_json", sa.Text(), nullable=True),
            sa.Column("validation_status", sa.String(20), nullable=False),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    _create_index_if_missing("ix_agent_logs_candidate_id", "agent_logs", ["candidate_id"])
    _create_index_if_missing("ix_agent_logs_created_at", "agent_logs", ["created_at"])
    _create_index_if_missing("ix_agent_logs_candidate", "agent_logs", ["candidate_id", "created_at"])

    if "system_logs" not in existing:
        op.create_table(
            "system_logs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("level", sa.String(20), nullable=False),
            sa.Column("event_code", sa.String(50), nullable=False),
            sa.Column("message_redacted", sa.Text(), nullable=False),
            sa.Column("correlation_id", sa.String(36), nullable=True),
            sa.Column("trade_id", sa.String(36), nullable=True),
            sa.Column("symbol", sa.String(20), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    _create_index_if_missing("ix_system_logs_event_code", "system_logs", ["event_code"])
    _create_index_if_missing("ix_system_logs_correlation_id", "system_logs", ["correlation_id"])
    _create_index_if_missing("ix_system_logs_created_at", "system_logs", ["created_at"])

    if "engine_state" not in existing:
        op.create_table(
            "engine_state",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("state", sa.String(30), nullable=False),
            sa.Column("environment", sa.String(20), nullable=False),
            sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
        )
    _create_index_if_missing("ix_engine_state_state", "engine_state", ["state"])

    if "audit_events" not in existing:
        op.create_table(
            "audit_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("actor", sa.String(100), nullable=False),
            sa.Column("action", sa.String(100), nullable=False),
            sa.Column("before_json", sa.Text(), nullable=True),
            sa.Column("after_json", sa.Text(), nullable=True),
            sa.Column("correlation_id", sa.String(36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    _create_index_if_missing("ix_audit_events_action", "audit_events", ["action"])
    _create_index_if_missing("ix_audit_events_created_at", "audit_events", ["created_at"])

    if "equity_snapshots" not in existing:
        op.create_table(
            "equity_snapshots",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("wallet_balance", sa.Numeric(20, 8), nullable=False),
            sa.Column("account_equity", sa.Numeric(20, 8), nullable=False),
            sa.Column("available_balance", sa.Numeric(20, 8), nullable=False),
            sa.Column("unrealized_pnl", sa.Numeric(20, 8), nullable=False),
            sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        )
    _create_index_if_missing("ix_equity_snapshots_captured_at", "equity_snapshots", ["captured_at"])

    if "margin_scaling_events" not in existing:
        op.create_table(
            "margin_scaling_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("closed_trade_id", sa.String(36), sa.ForeignKey("trades.id"), nullable=False),
            sa.Column("base_margin", sa.Numeric(20, 8), nullable=False),
            sa.Column("realized_net_profit", sa.Numeric(20, 8), nullable=False),
            sa.Column("reinvestment_pct", sa.Numeric(10, 4), nullable=False),
            sa.Column("next_margin", sa.Numeric(20, 8), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )

    if "symbol_metadata" not in existing:
        op.create_table(
            "symbol_metadata",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("symbol", sa.String(20), nullable=False, unique=True),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("contract_type", sa.String(30), nullable=False),
            sa.Column("margin_asset", sa.String(20), nullable=False),
            sa.Column("price_precision", sa.Integer(), nullable=False),
            sa.Column("quantity_precision", sa.Integer(), nullable=False),
            sa.Column("price_tick", sa.Numeric(20, 8), nullable=False),
            sa.Column("qty_step", sa.Numeric(20, 8), nullable=False),
            sa.Column("min_qty", sa.Numeric(20, 8), nullable=False),
            sa.Column("min_notional", sa.Numeric(20, 8), nullable=False),
            sa.Column("max_qty", sa.Numeric(20, 8), nullable=True),
            sa.Column("is_eligible", sa.Boolean(), nullable=False),
            sa.Column("ineligibility_reason", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    _create_index_if_missing("ix_symbol_metadata_symbol", "symbol_metadata", ["symbol"], unique=True)


def downgrade() -> None:
    existing = _existing_tables()
    for table in [
        "margin_scaling_events",
        "orders",
        "agent_logs",
        "trades",
        "signal_candidates",
        "symbol_metadata",
        "equity_snapshots",
        "audit_events",
        "engine_state",
        "system_logs",
        "exchange_credentials",
        "app_config",
    ]:
        if table in existing:
            op.drop_table(table)
