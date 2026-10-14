package com.ayo.paymenthelper;
import android.app.Notification;
import android.content.*;
import android.os.Bundle;
import android.service.notification.*;

public final class PaymentListener extends NotificationListenerService {
    public void onListenerConnected(){
        SecureStore.prefs(this).edit().putBoolean("listener_connected",true).apply();
        if(SecureStore.enabled(this)){
            try{for(StatusBarNotification n:getActiveNotifications())capture(n);}catch(Exception ignored){}
            SyncEngine.schedule(this);SyncEngine.kick(this,null);
            KeepAliveService.start(this);
        }
    }
    public void onListenerDisconnected(){
        SecureStore.prefs(this).edit().putBoolean("listener_connected",false).apply();
        if(SecureStore.enabled(this))requestRebind(new ComponentName(this,PaymentListener.class));
    }
    public void onNotificationPosted(StatusBarNotification n){capture(n);}
    private void capture(StatusBarNotification n){
        if(n==null||!TrustedApp.PACKAGE.equals(n.getPackageName())||!SecureStore.enabled(this))return;
        if(!TrustedApp.matches(this)){SecureStore.status(this,"Easypaisa app signature changed or is not trusted. Review setup.");return;}
        // Never import notifications older than this device's explicit capture enrollment.
        if(n.getPostTime()<SecureStore.prefs(this).getLong("capture_since",Long.MAX_VALUE))return;
        Bundle b=n.getNotification().extras;
        if(b==null)return;
        CharSequence big=b.getCharSequence(Notification.EXTRA_BIG_TEXT);
        CharSequence small=b.getCharSequence(Notification.EXTRA_TEXT);
        PaymentParser.Payment p=PaymentParser.parse(big==null?null:big.toString());
        if(p==null)p=PaymentParser.parse(small==null?null:small.toString());
        if(p==null){
            String candidate=(big!=null?big:(small!=null?small:"")).toString();
            if(candidate.contains("Trx ID")&&candidate.contains("Received"))
                SecureStore.status(this,"Payment format not recognized. Check wallet manually; nothing uploaded.");
            return;
        }
        try{
            if(QueueDb.get(this).enqueue(p,n.getPostTime())){
                SecureStore.status(this,"Payment captured. Upload queued.");
                SyncEngine.schedule(this);SyncEngine.kick(this,null);
            }
        }catch(Exception e){SecureStore.status(this,"Could not save payment locally. Check storage and review wallet.");}
    }
}
