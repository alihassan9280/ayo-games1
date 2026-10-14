package com.ayo.paymenthelper;
import android.content.*;
import android.database.Cursor;
import android.database.sqlite.*;
import java.util.*;

/** Durable upload queue + local payment history (amount, sender, masked number, state). */
public final class QueueDb extends SQLiteOpenHelper {
    private static QueueDb instance;
    public static synchronized QueueDb get(Context c){if(instance==null)instance=new QueueDb(c.getApplicationContext());return instance;}
    private QueueDb(Context c){super(c,"ayo_payments_v2.db",null,1);}
    public void onCreate(SQLiteDatabase db){
        db.execSQL("CREATE TABLE queue (tid TEXT PRIMARY KEY, payload TEXT NOT NULL, observed INTEGER NOT NULL, state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0, next_at INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '', added INTEGER NOT NULL, amount INTEGER NOT NULL DEFAULT 0, sender TEXT NOT NULL DEFAULT '', account TEXT NOT NULL DEFAULT '', synced_at INTEGER NOT NULL DEFAULT 0)");
    }
    public void onUpgrade(SQLiteDatabase db,int old,int next){}
    public synchronized boolean enqueue(PaymentParser.Payment p,long observed)throws Exception{
        try(Cursor c=getReadableDatabase().rawQuery("SELECT tid FROM queue WHERE tid=?",new String[]{p.tid})){if(c.moveToFirst())return false;}
        ContentValues v=new ContentValues();v.put("tid",p.tid);v.put("payload",SecureStore.encrypt(p.text));v.put("observed",observed);v.put("added",System.currentTimeMillis());
        v.put("amount",p.paisa);v.put("sender",p.sender);v.put("account",p.account);
        return getWritableDatabase().insertWithOnConflict("queue",null,v,SQLiteDatabase.CONFLICT_IGNORE)!=-1;
    }
    public static final class Item { String tid,payload;long observed;int attempts; }
    public static final class Row { public String tid,state,error,sender,account;public long amount,observed; }
    public synchronized List<Item> ready(){
        List<Item> items=new ArrayList<>();
        try(Cursor c=getReadableDatabase().rawQuery("SELECT tid,payload,observed,attempts FROM queue WHERE state='pending' AND next_at<=? ORDER BY added LIMIT 25",new String[]{Long.toString(System.currentTimeMillis())})){
            while(c.moveToNext()){Item i=new Item();i.tid=c.getString(0);i.payload=c.getString(1);i.observed=c.getLong(2);i.attempts=c.getInt(3);items.add(i);}
        }
        return items;
    }
    public synchronized void sent(String tid){
        ContentValues v=new ContentValues();v.put("state","sent");v.put("error","");v.put("payload","");v.put("synced_at",System.currentTimeMillis());
        getWritableDatabase().update("queue",v,"tid=?",new String[]{tid});
    }
    public synchronized void failed(Item i,String message,boolean permanent){
        ContentValues v=new ContentValues();v.put("state",permanent?"failed":"pending");v.put("attempts",i.attempts+1);v.put("error",message);
        long delay=Math.min(3600000L,30000L*(1L<<Math.min(i.attempts,7)));
        v.put("next_at",System.currentTimeMillis()+delay);
        getWritableDatabase().update("queue",v,"tid=?",new String[]{i.tid});
    }
    public synchronized int count(String state){
        try(Cursor c=getReadableDatabase().rawQuery("SELECT count(*) FROM queue WHERE state=?",new String[]{state})){c.moveToFirst();return c.getInt(0);}
    }
    /** {count, paisa} of payments observed since the given time. */
    public synchronized long[] totalSince(long since){
        try(Cursor c=getReadableDatabase().rawQuery("SELECT count(*),coalesce(sum(amount),0) FROM queue WHERE observed>=?",new String[]{Long.toString(since)})){
            c.moveToFirst();return new long[]{c.getLong(0),c.getLong(1)};
        }
    }
    public synchronized List<Row> history(String query,int limit){
        List<Row> list=new ArrayList<>();
        String q=query==null?"":query.trim();
        try(Cursor c=getReadableDatabase().rawQuery("SELECT tid,state,error,sender,account,amount,observed FROM queue WHERE ?='' OR tid LIKE ? OR sender LIKE ? OR account LIKE ? ORDER BY observed DESC LIMIT "+limit,
                new String[]{q,"%"+q+"%","%"+q+"%","%"+q+"%"})){
            while(c.moveToNext()){Row r=new Row();r.tid=c.getString(0);r.state=c.getString(1);r.error=c.getString(2);r.sender=c.getString(3);r.account=c.getString(4);r.amount=c.getLong(5);r.observed=c.getLong(6);list.add(r);}
        }return list;
    }
    public synchronized void retry(){
        getWritableDatabase().execSQL("UPDATE queue SET state='pending',next_at=0,attempts=0 WHERE state!='sent'");
    }
    public synchronized void clear(){getWritableDatabase().delete("queue",null,null);}
}
