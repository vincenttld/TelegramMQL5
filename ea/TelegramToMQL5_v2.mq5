//+------------------------------------------------------------------+
//|                                                  TeleSignal.mq5  |
//|                                    Copyright 2026, trolardv      |
//|                                           Version 2.00           |
//+------------------------------------------------------------------+

#define VERSION "2.0"

#property copyright "trolardv"
#property version   VERSION
#property indicator_chart_window
#property indicator_buffers 0
#property indicator_plots   0

#include <JAson.mqh>
#include <Trade\Trade.mqh>

CTrade trade;
CJAVal JsonValue;

string filename = "signals.json";

input string lot_rules = ""; // XAUUSD=1,USDJPY=1.5,EURUSD=0.10
input double default_lot = 0.1;
input bool divide_lot = false;
input bool use_breakeven = true;
input int  max_trade = 2; // Nb de trades a ouvrir par signal (0 = 1 trade par TP du signal)
input int  max_tp = 1;    // Nb de trades qui recoivent un TP (0 = tous). Les trades au-dela sont des runners (TP=0 + BE)
input string inpcomment = "TeleSignal"; // Comment
input string symbol_suffix = ""; // Suffix à ajouter au symbole (ex: "-vip", ".m")

//+------------------------------------------------------------------+
//|                                                                  |
//+------------------------------------------------------------------+
int OnInit(){
   Print("Signal EA start");
   ENUM_ACCOUNT_MARGIN_MODE mm = (ENUM_ACCOUNT_MARGIN_MODE)AccountInfoInteger(ACCOUNT_MARGIN_MODE);
   if(mm != ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
      Print("⚠️ Account is NETTING. One position per symbol only — multi-TP legs will MERGE into a single position. Use a HEDGING account for separate TP positions.");
   
   if(StringLen(symbol_suffix) > 0)
      Print("🔧 Symbol suffix configured: '", symbol_suffix, "'");
   
   ReadSignalsAndExecute();
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//|                                                                  |
//+------------------------------------------------------------------+
void OnTick(){
   ReadSignalsAndExecute();
   if(use_breakeven) ManageBreakEven();
   Comment("Telegram to MQL5","\nVersion: " + VERSION);
}

//+------------------------------------------------------------------+
//|                                                                  |
//+------------------------------------------------------------------+
string GetFullSymbol(string base_symbol)
{
   // Nettoyer le symbole de base
   StringTrimLeft(base_symbol);
   StringTrimRight(base_symbol);
   
   // Si un suffixe est défini, vérifier si le symbole existe avec ce suffixe
   if(StringLen(symbol_suffix) > 0)
   {
      string full_symbol = base_symbol + symbol_suffix;
      
      // Vérifier si le symbole existe
      if(SymbolSelect(full_symbol, true))
         return full_symbol;
      
      // Vérifier si le symbole existe sans suffixe
      if(SymbolSelect(base_symbol, true))
         return base_symbol;
      
      // Si on arrive ici, le symbole n'existe ni avec ni sans suffixe
      Print("⚠️ Symbole introuvable: '", base_symbol, "' et '", full_symbol, "'");
      return "";
   }
   
   // Pas de suffixe, vérifier le symbole tel quel
   if(SymbolSelect(base_symbol, true))
      return base_symbol;
   
   Print("⚠️ Symbole introuvable: '", base_symbol, "'");
   return "";
}

//+------------------------------------------------------------------+
//|                                                                  |
//+------------------------------------------------------------------+
void ReadSignalsAndExecute(){
   ResetLastError();

   CJAVal root;
   string json_text;
   
   int handle=FileOpen(filename, FILE_READ|FILE_TXT|FILE_ANSI);
   if(handle == INVALID_HANDLE){
      Print("❌ Cannot open file: ", filename);
      Print("Error code ", GetLastError()); 
      return;
   }

   while(!FileIsEnding(handle))
        json_text += FileReadString(handle);

   FileClose(handle);   
   if(!root.Deserialize(json_text)){
      Print("❌ Failed to JSON.Deserialize");
      return;
   }

   int count = root.Size();

   for(int i = 0; i < count; i++){
      
      CJAVal sig = root[i];

      string base_symbol = sig["symbol"].ToStr();

      string action  = sig["action"].ToStr();
      if(action == "") action = "open"; // backward compatibility

      long index_pre = sig["index"].ToInt();
      if(sig["processed"].ToBool()) continue;

      // ===== CLOSE ACTION =====
      // Un signal "close" ferme les trades de l'EA. symbol vide = tous les symboles.
      // Traite AVANT la resolution du symbole car "symbol" peut etre vide.
      if(action == "close"){
         if(!IsToday(sig["date"].ToStr())) continue; // ne pas rejouer un close historique

         string close_symbol = "";
         StringTrimLeft(base_symbol);
         StringTrimRight(base_symbol);
         if(StringLen(base_symbol) > 0){
            close_symbol = GetFullSymbol(base_symbol);
            if(close_symbol == ""){
               Print("❌ Close: symbole '", base_symbol, "' non trouvé sur le broker → signal ignoré");
               MarkSignalAsProcessed((int)index_pre);
               continue;
            }
         }

         if(CloseAllTrades(close_symbol))
            MarkSignalAsProcessed((int)index_pre);
         continue;
      }

      // ===== BREAK EVEN ACTION =====
      // Un signal "breakeven" passe le SL a l'entree sur les trades de l'EA.
      // symbol vide = tous les symboles. Traite AVANT la resolution du symbole.
      if(action == "breakeven"){
         if(!IsToday(sig["date"].ToStr())) continue; // ne pas rejouer un breakeven historique

         string be_symbol = "";
         StringTrimLeft(base_symbol);
         StringTrimRight(base_symbol);
         if(StringLen(base_symbol) > 0){
            be_symbol = GetFullSymbol(base_symbol);
            if(be_symbol == ""){
               Print("❌ BreakEven: symbole '", base_symbol, "' non trouvé sur le broker → signal ignoré");
               MarkSignalAsProcessed((int)index_pre);
               continue;
            }
         }

         if(ApplyBreakEven(be_symbol))
            MarkSignalAsProcessed((int)index_pre);
         continue;
      }

      StringTrimLeft(base_symbol);
      StringTrimRight(base_symbol);

      // Signal malforme : sans symbole on ne peut rien ouvrir.
      // Marque comme traite pour ne pas re-logger l'erreur a chaque tick.
      if(StringLen(base_symbol) == 0){
         Print("❌ Signal #", (int)index_pre, " action='", action, "' sans symbole → ignoré");
         MarkSignalAsProcessed((int)index_pre);
         continue;
      }

      string symbol = GetFullSymbol(base_symbol);

      // Si le symbole n'existe pas sur le broker, on passe
      if(symbol == "")
      {
         Print("❌ Symbole '", base_symbol, "' non trouvé sur le broker (suffixe configuré: '", symbol_suffix, "')");
         continue;
      }

      int type       = sig["type"].ToInt();
      double vol     = GetLotForSymbol(symbol);
      double entry   = sig["entry"].ToDbl();
      double sl      = sig["sl"].ToDbl();
      string date    = sig["date"].ToStr();
      string comment = inpcomment;
      long index     = sig["index"].ToInt();

      string final_comment = comment + "#" + IntegerToString(index);
      CJAVal tpArr = sig["tp"];
      double tps[];
      string tps_str="";
      int tpCount = tpArr.Size();
      ArrayResize(tps, tpCount);
      for(int j=0; j<tpCount; j++){
         tps[j] = tpArr[j].ToDbl();
         tps_str += NormalizeDouble(DoubleToString(tpArr[j].ToDbl()), SymbolInfoInteger(symbol, SYMBOL_DIGITS)) + " ";
      }
      ArraySort(tps); // ascending
      // leg1 must be the NEAREST TP (first to hit): ascending for BUY,
      // descending for SELL (its targets sit below entry).
      if(type == 2){
         for(int a = 0, b = tpCount - 1; a < b; a++, b--){
            double tmp = tps[a]; tps[a] = tps[b]; tps[b] = tmp;
         }
      }

      if(!IsToday(date)){
         continue;
      }

      if(divide_lot) vol = vol / 2;

      string msg;
      StringConcatenate(msg,
         "Signal #", IntegerToString(i), " → ",
         "Symbol=", symbol,
         " (base: ", base_symbol, ")",
         ", Type=", (type == 1 ? "BUY" : "SELL"),
         ", Volume=", DoubleToString(vol),
         ", Entry=", DoubleToString(entry),
         ", SL=", DoubleToString(sl),
         ", TPs=", tps_str,
         ", Date: ", date
      );
      Print(msg + ", Comment: ", final_comment);

      // ===== TRADE / TP ALLOCATION =====
      // max_trade  = nombre de positions ouvertes pour ce signal.
      // max_tp     = nombre de ces positions qui portent un TP (TP1, TP2, ... dans l'ordre).
      //              Les positions au-dela sont des runners (TP=0) gerees par le break-even.
      // Ex: max_trade=3, max_tp=2 -> leg1=TP1, leg2=TP2, leg3=runner.
      int legs = (max_trade > 0) ? max_trade : ((tpCount > 0) ? tpCount : 1);

      // On ne peut pas placer plus de TP qu'il n'y a de TP dans le signal ni de legs ouvertes.
      int tp_cap = (max_tp > 0) ? max_tp : legs;
      if(tp_cap > tpCount) tp_cap = tpCount;
      if(tp_cap > legs)    tp_cap = legs;

      bool all_ok = true;
      int  opened  = 0;

      for(int k = 0; k < legs; k++){
         double tp_k     = (k < tp_cap) ? tps[k] : 0;
         string leg_comment = final_comment + "-" + IntegerToString(k + 1);

         if(IsSignalAlreadyExecuted(leg_comment)){
            Print("Leg ", k + 1, "/", legs, " already executed → skip | ", leg_comment);
            continue;
         }

         Print("Leg ", k + 1, "/", legs, " → open ", symbol,
               (tp_k > 0 ? " TP=" + DoubleToString(tp_k) : " TP=none (runner + BE)"),
               " | ", leg_comment);
         if(OpenTrade(symbol, type, vol, entry, sl, tp_k, 0, leg_comment))
            opened++;
         else
            all_ok = false;
      }

      // Notification Telegram uniquement si au moins une position/ordre est reellement passe
      if(opened > 0)
         SendMessage(msg + " | " + IntegerToString(opened) + "/" + IntegerToString(legs) + " leg(s) OK");

      if(all_ok){
         MarkSignalAsProcessed((int)index);
      }

   }
}

//+------------------------------------------------------------------+
//| CLOSE ALL TRADES OF THIS EA                                      |
//| symbol == "" -> tous les symboles                                |
//+------------------------------------------------------------------+
bool CloseAllTrades(string symbol)
{
   bool all_ok = true;
   int  closed = 0, deleted = 0;

   //--- Positions ouvertes (boucle inversee : l'index bouge a chaque fermeture)
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(!PositionSelectByTicket(ticket)) continue;

      string pos_symbol = PositionGetString(POSITION_SYMBOL);
      if(symbol != "" && pos_symbol != symbol) continue;
      // On ne touche qu'aux trades issus des signaux Telegram
      if(StringFind(PositionGetString(POSITION_COMMENT), inpcomment) == -1) continue;

      if(trade.PositionClose(ticket)){
         closed++;
         Print("✅ Close position #", ticket, " ", pos_symbol);
      }
      else{
         all_ok = false;
         Print("❌ Close position #", ticket, " failed | ", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
      }
   }

   //--- Ordres en attente (limit/stop non declenches)
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0) continue;
      if(!OrderSelect(ticket)) continue;

      string ord_symbol = OrderGetString(ORDER_SYMBOL);
      if(symbol != "" && ord_symbol != symbol) continue;
      if(StringFind(OrderGetString(ORDER_COMMENT), inpcomment) == -1) continue;

      if(trade.OrderDelete(ticket)){
         deleted++;
         Print("✅ Delete pending #", ticket, " ", ord_symbol);
      }
      else{
         all_ok = false;
         Print("❌ Delete pending #", ticket, " failed | ", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
      }
   }

   string scope = (symbol == "" ? "ALL SYMBOLS" : symbol);
   string msg = "CLOSE signal (" + scope + ") → " + IntegerToString(closed) +
                " position(s) fermee(s), " + IntegerToString(deleted) + " ordre(s) supprime(s)";
   Print(msg);
   SendMessage(msg);

   return all_ok;
}

//+------------------------------------------------------------------+
//| MOVE SL TO ENTRY (BREAK EVEN) ON THIS EA'S TRADES                 |
//| symbol == "" -> tous les symboles                                |
//| BUY  : seulement si Ask > prix d'entree                          |
//| SELL : seulement si Bid < prix d'entree                          |
//| Retourne true quand toutes les positions concernees sont a BE    |
//| (sinon on re-tente au tick suivant, le temps que le prix bouge). |
//+------------------------------------------------------------------+
bool ApplyBreakEven(string symbol)
{
   int matched = 0, moved = 0, failed = 0, pending = 0;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(!PositionSelectByTicket(ticket)) continue;

      string pos_symbol = PositionGetString(POSITION_SYMBOL);
      if(symbol != "" && pos_symbol != symbol) continue;
      // On ne touche qu'aux trades issus des signaux Telegram
      if(StringFind(PositionGetString(POSITION_COMMENT), inpcomment) == -1) continue;

      matched++;

      int    digits     = (int)SymbolInfoInteger(pos_symbol, SYMBOL_DIGITS);
      double point      = SymbolInfoDouble(pos_symbol, SYMBOL_POINT);
      double open_price = NormalizeDouble(PositionGetDouble(POSITION_PRICE_OPEN), digits);
      double cur_sl     = PositionGetDouble(POSITION_SL);
      double cur_tp     = PositionGetDouble(POSITION_TP);
      long   pos_type   = PositionGetInteger(POSITION_TYPE);

      // Deja a l'entree (ou mieux) -> rien a faire
      if(cur_sl > 0 && MathAbs(cur_sl - open_price) < point) continue;

      if(pos_type == POSITION_TYPE_BUY)
      {
         double ask = SymbolInfoDouble(pos_symbol, SYMBOL_ASK);
         if(ask <= open_price){ pending++; continue; }      // pas encore en profit
         if(cur_sl > 0 && cur_sl > open_price) continue;     // SL deja au-dessus de l'entree
      }
      else if(pos_type == POSITION_TYPE_SELL)
      {
         double bid = SymbolInfoDouble(pos_symbol, SYMBOL_BID);
         if(bid >= open_price){ pending++; continue; }       // pas encore en profit
         if(cur_sl > 0 && cur_sl < open_price) continue;     // SL deja en-dessous de l'entree
      }
      else continue;

      if(trade.PositionModify(ticket, open_price, cur_tp)){
         moved++;
         Print("✅ BreakEven #", ticket, " ", pos_symbol, " → SL=", DoubleToString(open_price, digits));
      }
      else{
         failed++;
         Print("❌ BreakEven #", ticket, " ", pos_symbol, " failed | ",
               trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
      }
   }

   string scope = (symbol == "" ? "ALL SYMBOLS" : symbol);
   string msg = "BREAKEVEN signal (" + scope + ") → " + IntegerToString(moved) +
                " position(s) a BE, " + IntegerToString(pending) + " en attente (hors profit), " +
                IntegerToString(failed) + " echec(s)";
   Print(msg);
   if(moved > 0 || failed > 0) SendMessage(msg);

   // Signal termine seulement si plus rien a faire : aucune position hors profit, aucun echec.
   return (failed == 0 && pending == 0);
}

//+------------------------------------------------------------------+
//|                                                                  |
//+------------------------------------------------------------------+
bool OpenTrade(string symbol, int type, double volume, double entry, double sl, double tp, int magic, string comment)
{
   if(!SymbolSelect(symbol, true)){
      Print("Symbole invalide: ", symbol);
      return false;
   }

   double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(symbol, SYMBOL_BID);

   ENUM_ORDER_TYPE order_type;
   double price;

   // ===== BUY =====
   if(type == 1)
   {
      if(entry <= 0) // Market
      {
         order_type = ORDER_TYPE_BUY;
         price = ask;
      }
      else if(entry < ask) // Buy Limit
      {
         order_type = ORDER_TYPE_BUY_LIMIT;
         price = entry;
      }
      else // entry > ask → Buy Stop
      {
         order_type = ORDER_TYPE_BUY_STOP;
         price = entry;
      }
   }
   // ===== SELL =====
   else if(type == 2)
   {
      if(entry <= 0) // Market
      {
         order_type = ORDER_TYPE_SELL;
         price = bid;
      }
      else if(entry > bid) // Sell Limit
      {
         order_type = ORDER_TYPE_SELL_LIMIT;
         price = entry;
      }
      else // entry < bid → Sell Stop
      {
         order_type = ORDER_TYPE_SELL_STOP;
         price = entry;
      }
   }
   else
   {
      return false;
   }

   bool result;
   // ===== EXECUTION =====
   if(order_type == ORDER_TYPE_BUY || order_type == ORDER_TYPE_SELL)
   {
      result = trade.PositionOpen(symbol, order_type, volume, price, sl, tp, comment);
   }
   else
   {
      result = trade.OrderOpen(symbol, order_type, volume, price, price,sl, tp, ORDER_TIME_GTC, 0, comment);
   }

   if(!result)
   {
      Print("Erreur ouverture trade: ", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
      return false;
   }
   else
   {
      Print("Ordre envoyé: ", EnumToString(order_type), " @ ", price);
      return true;
   }
}

//+------------------------------------------------------------------+
//| AUTO BREAK EVEN ON TP1                                           |
//+------------------------------------------------------------------+
int ParseLeg(string c, long &idx)
{
   int h = StringFind(c, "#");
   if(h < 0) return -1;
   int dash = StringFind(c, "-", h);
   if(dash < 0) return -1;

   idx = StringToInteger(StringSubstr(c, h + 1, dash - h - 1));
   return (int)StringToInteger(StringSubstr(c, dash + 1));
}

//+------------------------------------------------------------------+
//|                                                                  |
//+------------------------------------------------------------------+
bool IsPositionOpenWithComment(string marker)
{
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
   {
      ulong t = PositionGetTicket(i);
      if(!PositionSelectByTicket(t)) continue;
      if(StringFind(PositionGetString(POSITION_COMMENT), marker) != -1)
         return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//|                                                                  |
//+------------------------------------------------------------------+
void ManageBreakEven()
{
   if(!use_breakeven) return;

   int total = PositionsTotal();
   for(int i = total - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(!PositionSelectByTicket(ticket)) continue;

      string c = PositionGetString(POSITION_COMMENT);
      if(StringFind(c, inpcomment) == -1) continue;

      long idx;
      int leg = ParseLeg(c, idx);
      if(leg < 2) continue; // only later legs (TP2, TP3...) are moved to BE

      string sym        = PositionGetString(POSITION_SYMBOL);
      double point      = SymbolInfoDouble(sym, SYMBOL_POINT);
      int    digits     = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
      double open_price = NormalizeDouble(PositionGetDouble(POSITION_PRICE_OPEN), digits);
      double cur_sl     = PositionGetDouble(POSITION_SL);
      double cur_tp     = PositionGetDouble(POSITION_TP);

      if(cur_sl > 0 && MathAbs(cur_sl - open_price) < point) continue;

      string leg1_marker = inpcomment + "#" + IntegerToString((int)idx) + "-1";
      if(IsPositionOpenWithComment(leg1_marker)) continue;

      if(trade.PositionModify(ticket, open_price, cur_tp))
         Print("✅ Auto-BE | ", c, " → SL=", open_price, " (leg1 #", (int)idx, " closed on TP1)");
      else
         Print("❌ Auto-BE failed | ", c, " | ", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
   }
}

//+------------------------------------------------------------------+
//|                                                                  |
//+------------------------------------------------------------------+
bool IsToday(string date_str){
    datetime signal_time = StringToTime(date_str);
    if(signal_time <= 0)
        return false;

    datetime now = TimeCurrent();

    MqlDateTime sig, cur;
    TimeToStruct(signal_time, sig);
    TimeToStruct(now, cur);

    return (sig.year  == cur.year &&
            sig.mon   == cur.mon  &&
            sig.day   == cur.day);
}

//+------------------------------------------------------------------+
//|                                                                  |
//+------------------------------------------------------------------+
bool IsSignalAlreadyExecuted(string expected)
{
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(!PositionSelectByTicket(ticket))
         continue;

      string comment = PositionGetString(POSITION_COMMENT);
      if(StringFind(comment, expected) != -1)
         return true;
   }

   int orders = OrdersTotal();
   for(int i = 0; i < orders; i++)
   {
      ulong ticket = OrderGetTicket(i);
      if(!OrderSelect(ticket))
         continue;

      string comment = OrderGetString(ORDER_COMMENT);
      if(StringFind(comment, expected) != -1)
         return true;
   }

   datetime today_start = StringToTime(TimeToString(TimeCurrent(), TIME_DATE));
   datetime now = TimeCurrent();

   if(!HistorySelect(today_start, now))
      return false;

   int deals = HistoryDealsTotal();
   for(int i = 0; i < deals; i++)
   {
      ulong deal_ticket = HistoryDealGetTicket(i);
      if(deal_ticket == 0)
         continue;

      string comment = HistoryDealGetString(deal_ticket, DEAL_COMMENT);
      if(StringFind(comment, expected) != -1)
         return true;
   }

   return false;
}

//+------------------------------------------------------------------+
//|                                                                  |
//+------------------------------------------------------------------+
double GetLotForSymbol(string symbol)
{
   string rules[];
   int count = StringSplit(lot_rules, ',', rules);

   for(int i = 0; i < count; i++)
   {
      string pair[];
      
      if(StringSplit(rules[i], '=', pair) != 2)
         continue;

      string rule_symbol = pair[0];
      double rule_lot = StringToDouble(pair[1]);

      StringTrimLeft(rule_symbol);
      StringTrimRight(rule_symbol);

      if(rule_symbol == symbol)
         return rule_lot;
   }

   return default_lot;
}

//+------------------------------------------------------------------+
//|                                                                  |
//+------------------------------------------------------------------+
void MarkSignalAsProcessed(int signal_index)
{
   CJAVal root;
   string json_text;

   int handle = FileOpen(filename, FILE_READ|FILE_TXT|FILE_ANSI);
   if(handle == INVALID_HANDLE)
      return;

   while(!FileIsEnding(handle))
      json_text += FileReadString(handle);

   FileClose(handle);

   if(!root.Deserialize(json_text))
      return;

   for(int i = 0; i < root.Size(); i++)
   {
      if(root[i]["index"].ToInt() == signal_index)
      {
         root[i]["processed"] = true;
         break;
      }
   }

   int count = root.Size();
   string json = "[\n";
   for(int i = 0; i < count; i++)
   {
      CJAVal sig   = root[i];
      CJAVal tpArr = sig["tp"];
      int tpCount  = tpArr.Size();

      string sig_action = sig["action"].ToStr();
      if(sig_action == "") sig_action = "open";

      json += "    {\n";
      json += "        \"action\": \""   + sig_action + "\",\n";
      json += "        \"symbol\": \""   + sig["symbol"].ToStr() + "\",\n";

      // Un signal "close"/"breakeven" ne porte ni type/entry/sl/tp : on garde le record minimal
      if(sig_action == "close" || sig_action == "breakeven"){
         json += "        \"date\": \""     + sig["date"].ToStr() + "\",\n";
         json += "        \"index\": "      + IntegerToString((int)sig["index"].ToInt()) + ",\n";
         json += "        \"processed\": "  + (sig["processed"].ToBool() ? "true" : "false") + "\n";
         json += "    }";
         if(i < count - 1) json += ",";
         json += "\n";
         continue;
      }

      json += "        \"type\": "       + IntegerToString(sig["type"].ToInt()) + ",\n";
      json += "        \"entry\": "      + DoubleToString(sig["entry"].ToDbl()) + ",\n";
      json += "        \"sl\": "         + DoubleToString(sig["sl"].ToDbl()) + ",\n";
      json += "        \"tp\": [";
      for(int j = 0; j < tpCount; j++){
         json += DoubleToString(tpArr[j].ToDbl());
         if(j < tpCount - 1) json += ", ";
      }
      json += "],\n";
      json += "        \"date\": \""     + sig["date"].ToStr() + "\",\n";
      json += "        \"index\": "      + IntegerToString((int)sig["index"].ToInt()) + ",\n";
      json += "        \"processed\": "  + (sig["processed"].ToBool() ? "true" : "false") + "\n";
      json += "    }";
      if(i < count - 1) json += ",";
      json += "\n";
   }
   json += "]";

   handle = FileOpen(filename, FILE_WRITE|FILE_TXT|FILE_ANSI);
   if(handle == INVALID_HANDLE)
      return;
   FileWriteString(handle, json);
   FileClose(handle);
}

//+------------------------------------------------------------------+
//|                                                                  |
//+------------------------------------------------------------------+
void SendMessage(string Message){
   char data[];
   char res[];
   string resHeaders;
   
   const string TG_API_URL = "https://api.telegram.org/";
   const string chat_ID="";
   string botTkn="";
   const string url = TG_API_URL+"bot"+botTkn+"/sendmessage?chat_id="+chat_ID+"&text="+Message;
   Print(Message);
   
   WebRequest("POST", url, "", 10000, data, res, resHeaders);
}
//+------------------------------------------------------------------+