package com.ayo.paymenthelper;
import android.content.*;
import android.service.notification.NotificationListenerService;
public final class BootReceiver extends BroadcastReceiver{
    public void onReceive(Context c,Intent i){
        if(SecureStore.enabled(c)){
            SyncEngine.schedule(c);
            KeepAliveService.start(c);
            NotificationListenerService.requestRebind(new ComponentName(c,PaymentListener.class));
        }
    }
}
