package com.ayo.paymenthelper;
import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.os.*;
import android.service.notification.NotificationListenerService;

/** Foreground service: keeps the process high priority so Android doesn't kill the payment bridge. */
public final class KeepAliveService extends Service {
    static final String CHANNEL="ayo_watch";
    private final Handler h=new Handler(Looper.getMainLooper());
    private final Runnable tick=new Runnable(){public void run(){
        if(!SecureStore.enabled(KeepAliveService.this)){stopSelf();return;}
        update();
        // keep the listener bound and the queue moving even if Android unbound it
        NotificationListenerService.requestRebind(new ComponentName(KeepAliveService.this,PaymentListener.class));
        SyncEngine.kick(KeepAliveService.this,null);
        h.postDelayed(this,5*60*1000L);
    }};

    public static void start(Context c){
        if(!SecureStore.enabled(c))return;
        try{
            Intent i=new Intent(c,KeepAliveService.class);
            if(Build.VERSION.SDK_INT>=26)c.startForegroundService(i);else c.startService(i);
        }catch(Exception ignored){}   // background start can be refused; the app/boot/job retry later
    }
    public static void stop(Context c){c.stopService(new Intent(c,KeepAliveService.class));}

    public void onCreate(){
        super.onCreate();
        NotificationManager nm=(NotificationManager)getSystemService(NOTIFICATION_SERVICE);
        if(Build.VERSION.SDK_INT>=26){
            NotificationChannel ch=new NotificationChannel(CHANNEL,"Payment watch",NotificationManager.IMPORTANCE_LOW);
            ch.setShowBadge(false);nm.createNotificationChannel(ch);
        }
        Notification n=build();
        if(Build.VERSION.SDK_INT>=34)startForeground(7,n,ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        else startForeground(7,n);
    }
    public int onStartCommand(Intent i,int flags,int id){h.removeCallbacks(tick);h.post(tick);return START_STICKY;}
    public void onTaskRemoved(Intent root){start(getApplicationContext());super.onTaskRemoved(root);}
    public void onDestroy(){h.removeCallbacks(tick);super.onDestroy();}
    public IBinder onBind(Intent i){return null;}

    private Notification build(){
        QueueDb q=QueueDb.get(this);
        long[] today=q.totalSince(MainActivity.startOfToday());
        int pending=q.count("pending");
        String text="Today: "+today[0]+" payments · Rs "+MainActivity.money(today[1])+(pending>0?" · "+pending+" waiting to sync":" · all synced");
        PendingIntent open=PendingIntent.getActivity(this,0,new Intent(this,MainActivity.class),PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);
        Notification.Builder b=Build.VERSION.SDK_INT>=26?new Notification.Builder(this,CHANNEL):new Notification.Builder(this);
        return b.setSmallIcon(R.drawable.ic_stat).setContentTitle("AYO payment watch is active").setContentText(text)
            .setOngoing(true).setShowWhen(false).setContentIntent(open).setColor(0xFF0B7A3E).build();
    }
    private void update(){
        try{((NotificationManager)getSystemService(NOTIFICATION_SERVICE)).notify(7,build());}catch(Exception ignored){}
    }
}
