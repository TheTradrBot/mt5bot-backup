"""
MT5 Direct Client - For running directly on Windows VM with MT5.

This is the main client used by the standalone trading bot.
It directly imports MetaTrader5 library (Windows only).
"""

from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
import time


@dataclass
class TickData:
    """Represents a price tick."""
    symbol: str
    bid: float
    ask: float
    time: datetime
    spread: float


@dataclass
class Position:
    """Represents an open position."""
    ticket: int
    symbol: str
    type: int
    volume: float
    price_open: float
    sl: float
    tp: float
    profit: float
    time: datetime
    magic: int
    comment: str


@dataclass
class PendingOrder:
    """Represents a pending order."""
    ticket: int
    symbol: str
    type: int
    volume: float
    price: float
    sl: float
    tp: float
    time_setup: datetime
    expiration: datetime
    magic: int
    comment: str


@dataclass
class TradeResult:
    """Result of a trade operation."""
    success: bool
    order_id: int = 0
    deal_id: int = 0
    price: float = 0.0
    volume: float = 0.0
    error: str = ""


class MT5Client:
    """
    Direct MT5 client for Windows.
    
    This class directly interfaces with MetaTrader5.
    Only works on Windows with MT5 terminal installed.
    """
    
    MAGIC_NUMBER = 123456
    COMMENT = "TradrBot"
    
    def __init__(
        self,
        server: str = "",
        login: int = 0,
        password: str = "",
    ):
        self.server = server
        self.login = login
        self.password = password
        self.connected = False
        self._mt5 = None
    
    def _import_mt5(self):
        """Lazy import of MetaTrader5 (Windows only)."""
        if self._mt5 is None:
            try:
                import MetaTrader5 as mt5
                self._mt5 = mt5
            except ImportError:
                raise ImportError(
                    "MetaTrader5 library not available. "
                    "This client only works on Windows with MT5 installed."
                )
        return self._mt5
    
    def connect(self) -> bool:
        """Connect to MT5 terminal."""
        mt5 = self._import_mt5()
        
        if not mt5.initialize():
            error = mt5.last_error()
            print(f"[MT5] Initialize failed: {error}")
            return False
        
        if self.login and self.password and self.server:
            authorized = mt5.login(
                self.login,
                password=self.password,
                server=self.server
            )
            
            if not authorized:
                error = mt5.last_error()
                print(f"[MT5] Login failed: {error}")
                mt5.shutdown()
                return False
        
        self.connected = True
        account = mt5.account_info()
        print(f"[MT5] Connected: {account.login} @ {account.server}")
        print(f"[MT5] Balance: ${account.balance:,.2f}, Equity: ${account.equity:,.2f}")
        return True
    
    def disconnect(self):
        """Disconnect from MT5."""
        if self._mt5 and self.connected:
            self._mt5.shutdown()
        self.connected = False
    
    def get_account_info(self) -> Dict:
        """Get account information."""
        if not self.connected:
            return {}
        
        mt5 = self._import_mt5()
        info = mt5.account_info()
        
        if info is None:
            return {}
        
        return {
            "login": info.login,
            "server": info.server,
            "balance": info.balance,
            "equity": info.equity,
            "margin": info.margin,
            "free_margin": info.margin_free,
            "leverage": info.leverage,
            "currency": info.currency,
        }
    
    def get_tick(self, symbol: str) -> Optional[TickData]:
        """Get current tick for a symbol."""
        if not self.connected:
            return None
        
        mt5 = self._import_mt5()
        tick = mt5.symbol_info_tick(symbol)
        
        if tick is None:
            return None
        
        return TickData(
            symbol=symbol,
            bid=tick.bid,
            ask=tick.ask,
            time=datetime.fromtimestamp(tick.time, tz=timezone.utc),
            spread=tick.ask - tick.bid,
        )
    
    def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "D1",
        count: int = 100,
    ) -> List[Dict]:
        """Get OHLCV candle data."""
        if not self.connected:
            return []
        
        mt5 = self._import_mt5()
        
        timeframe_map = {
            "M1": mt5.TIMEFRAME_M1,
            "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "M30": mt5.TIMEFRAME_M30,
            "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4,
            "D1": mt5.TIMEFRAME_D1,
            "D": mt5.TIMEFRAME_D1,
            "W1": mt5.TIMEFRAME_W1,
            "W": mt5.TIMEFRAME_W1,
            "MN1": mt5.TIMEFRAME_MN1,
            "M": mt5.TIMEFRAME_MN1,
        }
        
        tf = timeframe_map.get(timeframe.upper(), mt5.TIMEFRAME_D1)
        
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
        
        if rates is None:
            return []
        
        candles = []
        for rate in rates:
            candles.append({
                "time": datetime.fromtimestamp(rate[0], tz=timezone.utc),
                "open": rate[1],
                "high": rate[2],
                "low": rate[3],
                "close": rate[4],
                "volume": rate[5],
            })
        
        return candles
    
    def execute_trade(
        self,
        symbol: str,
        direction: str,
        volume: float,
        sl: float,
        tp: float,
        deviation: int = 20,
    ) -> TradeResult:
        """Execute a market order."""
        if not self.connected:
            return TradeResult(success=False, error="Not connected")
        
        mt5 = self._import_mt5()
        
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return TradeResult(success=False, error=f"Cannot get tick for {symbol}")
        
        if direction.lower() == "bullish":
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask
        else:
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid
        
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": deviation,
            "magic": self.MAGIC_NUMBER,
            "comment": self.COMMENT,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        
        result = mt5.order_send(request)
        
        if result is None:
            return TradeResult(success=False, error="Order send returned None")
        
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return TradeResult(
                success=False,
                error=f"Order failed: {result.comment} (code: {result.retcode})"
            )
        
        return TradeResult(
            success=True,
            order_id=result.order,
            deal_id=result.deal,
            price=result.price,
            volume=result.volume,
        )
    
    def close_position(self, ticket: int) -> TradeResult:
        """Close a position by ticket."""
        if not self.connected:
            return TradeResult(success=False, error="Not connected")
        
        mt5 = self._import_mt5()
        
        position = mt5.positions_get(ticket=ticket)
        if not position:
            return TradeResult(success=False, error=f"Position {ticket} not found")
        
        position = position[0]
        symbol = position.symbol
        volume = position.volume
        
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return TradeResult(success=False, error=f"Cannot get tick for {symbol}")
        
        if position.type == mt5.ORDER_TYPE_BUY:
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid
        else:
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask
        
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "position": ticket,
            "price": price,
            "deviation": 20,
            "magic": self.MAGIC_NUMBER,
            "comment": "TradrBot Close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        
        result = mt5.order_send(request)
        
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            error = result.comment if result else "Unknown error"
            return TradeResult(success=False, error=error)
        
        return TradeResult(
            success=True,
            order_id=result.order,
            deal_id=result.deal,
            price=result.price,
            volume=result.volume,
        )
    
    def partial_close(self, ticket: int, volume: float) -> TradeResult:
        """
        Partially close a position by volume.
        
        Args:
            ticket: Position ticket number
            volume: Volume to close (must be <= position volume)
            
        Returns:
            TradeResult with success status and details
        """
        if not self.connected:
            return TradeResult(success=False, error="Not connected")
        
        mt5 = self._import_mt5()
        
        position = mt5.positions_get(ticket=ticket)
        if not position:
            return TradeResult(success=False, error=f"Position {ticket} not found")
        
        position = position[0]
        symbol = position.symbol
        current_volume = position.volume
        
        if volume > current_volume:
            return TradeResult(
                success=False,
                error=f"Requested volume {volume} exceeds position volume {current_volume}"
            )
        
        close_volume = round(volume, 2)
        if close_volume < 0.01:
            close_volume = 0.01
        
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return TradeResult(success=False, error=f"Cannot get tick for {symbol}")
        
        if position.type == mt5.ORDER_TYPE_BUY:
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid
        else:
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask
        
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": close_volume,
            "type": order_type,
            "position": ticket,
            "price": price,
            "deviation": 20,
            "magic": self.MAGIC_NUMBER,
            "comment": "TradrBot PartialClose",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        
        result = mt5.order_send(request)
        
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            error = result.comment if result else "Unknown error"
            return TradeResult(success=False, error=f"Partial close failed: {error}")
        
        return TradeResult(
            success=True,
            order_id=result.order,
            deal_id=result.deal,
            price=result.price,
            volume=result.volume,
        )
    
    def get_positions(self, symbol: str = None) -> List[Position]:
        """Get open positions."""
        if not self.connected:
            return []
        
        mt5 = self._import_mt5()
        
        if symbol:
            positions = mt5.positions_get(symbol=symbol)
        else:
            positions = mt5.positions_get()
        
        if positions is None:
            return []
        
        result = []
        for pos in positions:
            result.append(Position(
                ticket=pos.ticket,
                symbol=pos.symbol,
                type=pos.type,
                volume=pos.volume,
                price_open=pos.price_open,
                sl=pos.sl,
                tp=pos.tp,
                profit=pos.profit,
                time=datetime.fromtimestamp(pos.time, tz=timezone.utc),
                magic=pos.magic,
                comment=pos.comment,
            ))
        
        return result
    
    def get_my_positions(self) -> List[Position]:
        """Get positions opened by this bot (by magic number)."""
        all_positions = self.get_positions()
        return [p for p in all_positions if p.magic == self.MAGIC_NUMBER]
    
    def modify_sl_tp(
        self,
        ticket: int,
        sl: float = None,
        tp: float = None,
    ) -> bool:
        """Modify stop loss and/or take profit of a position."""
        if not self.connected:
            return False
        
        mt5 = self._import_mt5()
        
        position = mt5.positions_get(ticket=ticket)
        if not position:
            return False
        
        position = position[0]
        
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": position.symbol,
            "position": ticket,
            "sl": sl if sl is not None else position.sl,
            "tp": tp if tp is not None else position.tp,
        }
        
        result = mt5.order_send(request)
        
        return result is not None and result.retcode == mt5.TRADE_RETCODE_DONE
    
    def get_symbol_info(self, symbol: str) -> Optional[Dict]:
        """Get symbol information."""
        if not self.connected:
            return None
        
        mt5 = self._import_mt5()
        info = mt5.symbol_info(symbol)
        
        if info is None:
            return None
        
        return {
            "name": info.name,
            "digits": info.digits,
            "point": info.point,
            "spread": info.spread,
            "min_lot": info.volume_min,
            "max_lot": info.volume_max,
            "lot_step": info.volume_step,
            "contract_size": info.trade_contract_size,
        }
    
    def place_pending_order(
        self,
        symbol: str,
        direction: str,
        volume: float,
        entry_price: float,
        sl: float,
        tp: float,
        expiration_hours: int = 24,
    ) -> TradeResult:
        """
        Place a pending limit/stop order.
        
        For bullish: BUY_LIMIT if entry < ask, else BUY_STOP
        For bearish: SELL_LIMIT if entry > bid, else SELL_STOP
        """
        if not self.connected:
            return TradeResult(success=False, error="Not connected")
        
        mt5 = self._import_mt5()
        
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return TradeResult(success=False, error=f"Cannot get tick for {symbol}")
        
        if direction.lower() == "bullish":
            if entry_price < tick.ask:
                order_type = mt5.ORDER_TYPE_BUY_LIMIT
            else:
                order_type = mt5.ORDER_TYPE_BUY_STOP
        else:
            if entry_price > tick.bid:
                order_type = mt5.ORDER_TYPE_SELL_LIMIT
            else:
                order_type = mt5.ORDER_TYPE_SELL_STOP
        
        expiration_time = datetime.now(timezone.utc) + timedelta(hours=expiration_hours)
        expiration_timestamp = int(expiration_time.timestamp())
        
        request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": entry_price,
            "sl": sl,
            "tp": tp,
            "magic": self.MAGIC_NUMBER,
            "comment": self.COMMENT,
            "type_time": mt5.ORDER_TIME_SPECIFIED,
            "expiration": expiration_timestamp,
            "type_filling": mt5.ORDER_FILLING_RETURN,
        }
        
        result = mt5.order_send(request)
        
        if result is None:
            return TradeResult(success=False, error="Order send returned None")
        
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return TradeResult(
                success=False,
                error=f"Pending order failed: {result.comment} (code: {result.retcode})"
            )
        
        return TradeResult(
            success=True,
            order_id=result.order,
            price=entry_price,
            volume=volume,
        )
    
    def cancel_pending_order(self, ticket: int) -> bool:
        """Cancel a pending order by ticket."""
        if not self.connected:
            return False
        
        mt5 = self._import_mt5()
        
        request = {
            "action": mt5.TRADE_ACTION_REMOVE,
            "order": ticket,
        }
        
        result = mt5.order_send(request)
        
        return result is not None and result.retcode == mt5.TRADE_RETCODE_DONE
    
    def get_pending_orders(self, symbol: str = None) -> List[PendingOrder]:
        """Get pending orders, optionally filtered by symbol."""
        if not self.connected:
            return []
        
        mt5 = self._import_mt5()
        
        if symbol:
            orders = mt5.orders_get(symbol=symbol)
        else:
            orders = mt5.orders_get()
        
        if orders is None:
            return []
        
        result = []
        for order in orders:
            exp_time = datetime.fromtimestamp(order.time_expiration, tz=timezone.utc) if order.time_expiration > 0 else datetime.max.replace(tzinfo=timezone.utc)
            result.append(PendingOrder(
                ticket=order.ticket,
                symbol=order.symbol,
                type=order.type,
                volume=order.volume_current,
                price=order.price_open,
                sl=order.sl,
                tp=order.tp,
                time_setup=datetime.fromtimestamp(order.time_setup, tz=timezone.utc),
                expiration=exp_time,
                magic=order.magic,
                comment=order.comment,
            ))
        
        return result
    
    def get_my_pending_orders(self) -> List[PendingOrder]:
        """Get pending orders placed by this bot (by magic number)."""
        all_orders = self.get_pending_orders()
        return [o for o in all_orders if o.magic == self.MAGIC_NUMBER]
