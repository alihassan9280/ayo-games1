package com.ayo.paymenthelper;

import android.Manifest;
import android.animation.ObjectAnimator;
import android.animation.ValueAnimator;
import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.*;
import android.provider.Settings;
import android.service.notification.NotificationListenerService;
import android.text.Editable;
import android.text.InputType;
import android.text.TextWatcher;
import android.view.*;
import android.widget.*;
import java.text.DateFormat;
import java.text.DecimalFormat;
import java.util.*;

public final class MainActivity extends Activity {
    static final int G=Color.rgb(11,122,62),G2=Color.rgb(18,161,80),BG=Color.rgb(238,243,240),CARD=Color.WHITE,
        INK=Color.rgb(20,36,27),MUTED=Color.rgb(98,115,106),LINE=Color.rgb(225,232,228),RED=Color.rgb(192,54,44),AMBER=Color.rgb(168,107,0);
    private LinearLayout body,checks,history;
    private TextView status,todayAmt,todayCount,last,pendingInfo;
    private View pulse;
    private EditText url,device,token,search;
    private Button pause;
    private final Handler handler=new Handler(Looper.getMainLooper());
    private final Runnable refreshTask=new Runnable(){public void run(){refresh();handler.postDelayed(this,2000);}};

    public void onCreate(Bundle state){
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        ScrollView scroll=new ScrollView(this);scroll.setFillViewport(true);scroll.setBackgroundColor(BG);
        LinearLayout root=new LinearLayout(this);root.setOrientation(LinearLayout.VERTICAL);scroll.addView(root);
        scroll.setOnApplyWindowInsetsListener((v,insets)->{root.setPadding(0,0,0,insets.getSystemWindowInsetBottom());return insets;});
        setContentView(scroll);

        LinearLayout hero=new LinearLayout(this);hero.setOrientation(LinearLayout.VERTICAL);hero.setPadding(dp(22),dp(30),dp(22),dp(58));
        hero.setBackground(new GradientDrawable(GradientDrawable.Orientation.TL_BR,new int[]{Color.rgb(7,90,45),G2}));
        root.addView(hero);
        LinearLayout top=new LinearLayout(this);top.setGravity(Gravity.CENTER_VERTICAL);hero.addView(top);
        pulse=new View(this);GradientDrawable pd=new GradientDrawable();pd.setShape(GradientDrawable.OVAL);pd.setColor(Color.rgb(140,255,190));pulse.setBackground(pd);
        top.addView(pulse,new LinearLayout.LayoutParams(dp(10),dp(10)));
        top.addView(text("  AYO · PAYMENT HELPER",12,Color.WHITE,true));
        ObjectAnimator an=ObjectAnimator.ofFloat(pulse,"alpha",1f,.25f);an.setDuration(900);an.setRepeatCount(ValueAnimator.INFINITE);an.setRepeatMode(ValueAnimator.REVERSE);an.start();
        TextView lt=text("Received today",13,Color.argb(210,255,255,255),false);lt.setPadding(0,dp(18),0,0);hero.addView(lt);
        todayAmt=text("Rs 0.00",34,Color.WHITE,true);hero.addView(todayAmt);
        todayCount=text("0 payments",13,Color.argb(210,255,255,255),false);hero.addView(todayCount);

        body=new LinearLayout(this);body.setOrientation(LinearLayout.VERTICAL);body.setPadding(dp(16),0,dp(16),dp(28));
        LinearLayout.LayoutParams bp=new LinearLayout.LayoutParams(-1,-2);bp.topMargin=-dp(40);root.addView(body,bp);

        LinearLayout st=card(false);
        label(st,"STATUS",11,G,true);
        status=label(st,"Not connected",17,INK,true);
        pendingInfo=label(st,"",13,MUTED,false);
        last=label(st,"",12,MUTED,false);
        LinearLayout r1=new LinearLayout(this);st.addView(r1);
        button(r1,"Sync now",()->{if(!SecureStore.enabled(this)){message("Connect your server first.");return;}SecureStore.status(this,"Connecting…");refresh();SyncEngine.schedule(this);SyncEngine.kick(this,null);KeepAliveService.start(this);},true,1);
        pause=button(r1,"Pause",()->togglePause(),false,1);

        LinearLayout hc=card(true);
        label(hc,"Never miss a payment",18,INK,true);
        label(hc,"Tap any red item to fix it. All green means payments are captured even when the app is closed.",13,MUTED,false);
        checks=new LinearLayout(this);checks.setOrientation(LinearLayout.VERTICAL);hc.addView(checks);

        LinearLayout hi=card(true);
        label(hi,"Payment history",18,INK,true);
        search=input(hi,"Search Trx ID, name or number",false);
        search.addTextChangedListener(new TextWatcher(){public void beforeTextChanged(CharSequence s,int a,int b,int c){}public void onTextChanged(CharSequence s,int a,int b,int c){}public void afterTextChanged(Editable e){renderHistory();}});
        history=new LinearLayout(this);history.setOrientation(LinearLayout.VERTICAL);hi.addView(history);
        button(hi,"Retry failed uploads",()->{if(!SecureStore.enabled(this)){message("Connect your server first.");return;}QueueDb.get(this).retry();SyncEngine.schedule(this);SyncEngine.kick(this,null);refresh();},false,0);

        LinearLayout setup=card(true);
        label(setup,"Connect your server",18,INK,true);
        label(setup,"Use credentials from your gateway admin page. Never enter your Easypaisa PIN or OTP.",13,MUTED,false);
        url=input(setup,"HTTPS server URL (https://...)",false);
        device=input(setup,"Device ID",false);
        token=input(setup,"Device token",true);
        url.setText(SecureStore.prefs(this).getString("url",""));
        device.setText(SecureStore.prefs(this).getString("device",""));
        if(SecureStore.configured(this))token.setHint("Saved securely • leave blank to keep");
        button(setup,"Save & connect",()->save(),true,0);

        LinearLayout adv=card(true);
        label(adv,"More",18,INK,true);
        button(adv,"Trust installed Easypaisa",()->trustApp(),false,0);
        button(adv,"Enable Notification Access",()->notificationDisclosure(),false,0);
        button(adv,"Battery: allow background",()->requestBattery(),false,0);
        button(adv,"App settings",()->open(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,Uri.parse("package:"+getPackageName()))),false,0);
        button(adv,"Privacy & how it works",()->privacy(),false,0);
        button(adv,"Reset app data",()->reset(),false,0);
        label(body,"Independent helper · Not an official Easypaisa app · v2.0 · Android 8+",11,MUTED,false);

        if(Build.VERSION.SDK_INT>=33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED)
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS},1);
        if(SecureStore.enabled(this))KeepAliveService.start(this);
    }

    protected void onResume(){super.onResume();handler.post(refreshTask);}
    protected void onPause(){handler.removeCallbacks(refreshTask);super.onPause();}

    static long startOfToday(){
        Calendar c=Calendar.getInstance();c.set(Calendar.HOUR_OF_DAY,0);c.set(Calendar.MINUTE,0);c.set(Calendar.SECOND,0);c.set(Calendar.MILLISECOND,0);
        return c.getTimeInMillis();
    }
    static String money(long paisa){return new DecimalFormat("#,##0.00").format(paisa/100.0);}

    private int dp(int n){return (int)(n*getResources().getDisplayMetrics().density);}
    private TextView text(String s,int size,int color,boolean bold){
        TextView v=new TextView(this);v.setText(s);v.setTextSize(size);v.setTextColor(color);if(bold)v.setTypeface(Typeface.DEFAULT,Typeface.BOLD);return v;
    }
    private LinearLayout card(boolean margin){
        LinearLayout l=new LinearLayout(this);l.setOrientation(LinearLayout.VERTICAL);l.setPadding(dp(18),dp(16),dp(18),dp(18));
        GradientDrawable b=new GradientDrawable();b.setColor(CARD);b.setCornerRadius(dp(18));l.setBackground(b);l.setElevation(dp(2));
        LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2);p.topMargin=margin?dp(14):0;body.addView(l,p);return l;
    }
    private TextView label(LinearLayout parent,String s,int size,int color,boolean bold){
        TextView v=text(s,size,color,bold);v.setLineSpacing(dp(3),1);
        LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2);p.bottomMargin=dp(8);parent.addView(v,p);return v;
    }
    private EditText input(LinearLayout parent,String hint,boolean password){
        EditText e=new EditText(this);e.setSingleLine(true);e.setTextSize(14);e.setTextColor(INK);e.setHintTextColor(MUTED);e.setHint(hint);
        e.setInputType(password?InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD:InputType.TYPE_CLASS_TEXT);
        e.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
        GradientDrawable b=new GradientDrawable();b.setColor(Color.rgb(246,249,247));b.setCornerRadius(dp(12));b.setStroke(dp(1),LINE);e.setBackground(b);
        e.setPadding(dp(13),dp(13),dp(13),dp(13));
        LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2);p.topMargin=dp(5);p.bottomMargin=dp(5);parent.addView(e,p);return e;
    }
    private Button button(LinearLayout parent,String label,Runnable action,boolean primary,int weight){
        Button b=new Button(this);b.setText(label);b.setAllCaps(false);b.setTextSize(14);b.setTextColor(primary?Color.WHITE:G);b.setTypeface(Typeface.DEFAULT_BOLD);
        GradientDrawable d=new GradientDrawable();d.setColor(primary?G:Color.rgb(230,236,232));d.setCornerRadius(dp(12));b.setBackground(d);
        LinearLayout.LayoutParams p=weight>0?new LinearLayout.LayoutParams(0,-2,1):new LinearLayout.LayoutParams(-1,-2);
        p.topMargin=dp(6);p.bottomMargin=dp(6);p.leftMargin=dp(3);p.rightMargin=dp(3);b.setMinHeight(dp(50));
        parent.addView(b,p);b.setOnClickListener(v->action.run());return b;
    }

    private void checkRow(String title,boolean ok,String fixHint,Runnable fix){
        LinearLayout row=new LinearLayout(this);row.setGravity(Gravity.CENTER_VERTICAL);row.setPadding(0,dp(8),0,dp(8));
        View dot=new View(this);GradientDrawable g=new GradientDrawable();g.setShape(GradientDrawable.OVAL);g.setColor(ok?G2:RED);dot.setBackground(g);
        row.addView(dot,new LinearLayout.LayoutParams(dp(12),dp(12)));
        LinearLayout col=new LinearLayout(this);col.setOrientation(LinearLayout.VERTICAL);col.setPadding(dp(12),0,0,0);
        TextView t=text(title,15,INK,false);col.addView(t);
        if(!ok&&fixHint!=null)col.addView(text(fixHint,12,MUTED,false));
        row.addView(col,new LinearLayout.LayoutParams(0,-2,1));
        if(!ok&&fix!=null){TextView fixBtn=text("Fix",13,G,true);fixBtn.setPadding(dp(10),dp(6),dp(10),dp(6));row.addView(fixBtn);row.setOnClickListener(v->fix.run());}
        else row.addView(text(ok?"OK":"",13,G2,true));
        checks.addView(row);
        View sep=new View(this);sep.setBackgroundColor(LINE);checks.addView(sep,new LinearLayout.LayoutParams(-1,1));
    }

    private boolean notifAccess(){
        ComponentName listener=new ComponentName(this,PaymentListener.class);
        if(Build.VERSION.SDK_INT>=27)return ((NotificationManager)getSystemService(NOTIFICATION_SERVICE)).isNotificationListenerAccessGranted(listener);
        String s=Settings.Secure.getString(getContentResolver(),"enabled_notification_listeners");
        return s!=null&&Arrays.asList(s.split(":")).contains(listener.flattenToString());
    }
    private boolean batteryFree(){
        PowerManager pm=(PowerManager)getSystemService(POWER_SERVICE);
        return pm==null||pm.isIgnoringBatteryOptimizations(getPackageName());
    }

    private void save(){
        if(SyncEngine.isBusy()){message("Sync is running. Try again in a moment.");return;}
        try{
            String base=SyncEngine.normalizeUrl(url.getText().toString());
            String id=device.getText().toString().trim();
            if(!id.matches("[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"))throw new Exception("Enter the Device ID from your gateway.");
            SharedPreferences p=SecureStore.prefs(this);
            boolean changed=!base.equals(p.getString("url",""))||!id.equals(p.getString("device",""));
            if(changed&&(QueueDb.get(this).count("pending")+QueueDb.get(this).count("failed")>0))
                throw new Exception("Resolve queued payments before changing server/device.");
            String key=token.getText().toString().trim();
            if(key.isEmpty()&&!changed)key=SecureStore.token(this);
            if(!key.matches("[a-fA-F0-9]{64}"))throw new Exception("Paste the 64-character device token.");
            SharedPreferences.Editor edit=p.edit().putString("url",base).putString("device",id).putString("token",SecureStore.encrypt(key)).putBoolean("enabled",true);
            if(!p.getBoolean("enabled",false)||changed||p.getLong("capture_since",0)==0)edit.putLong("capture_since",System.currentTimeMillis());
            edit.commit();
            token.setText("");token.setHint("Saved securely • leave blank to keep");
            SecureStore.status(this,"Settings saved. Testing server…");
            SyncEngine.schedule(this);SyncEngine.kick(this,null);KeepAliveService.start(this);
            NotificationListenerService.requestRebind(new ComponentName(this,PaymentListener.class));
            refresh();
        }catch(Exception e){message(e.getMessage()==null?"Could not save settings.":e.getMessage());}
    }
    private void trustApp(){
        try{
            List<String> sigs=TrustedApp.signatures(this);
            if(sigs.isEmpty())throw new Exception();
            String pin=sigs.get(sigs.size()-1);
            new AlertDialog.Builder(this).setTitle("Trust your installed Easypaisa?")
                .setMessage("Continue only if you installed Easypaisa from the official Google Play listing. This pins its signing certificate.\n\nPackage: "+TrustedApp.PACKAGE+"\n\nSHA-256:\n"+pin)
                .setNegativeButton("Cancel",null).setPositiveButton("Trust",(d,w)->{SecureStore.prefs(this).edit().putString("signer",pin).commit();refresh();}).show();
        }catch(Exception e){message("Easypaisa is not installed or its certificate could not be read. Install the official Easypaisa app first.");}
    }
    private void notificationDisclosure(){
        new AlertDialog.Builder(this).setTitle("Payment notification access")
            .setMessage("This helper reads only recognized Easypaisa incoming-payment notifications (Transaction ID, amount, sender name, masked number) and sends them to your HTTPS server. It ignores OTPs and other apps. You can pause or revoke access any time.")
            .setNegativeButton("Cancel",null).setPositiveButton("Open settings",(d,w)->open(new Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))).show();
    }
    private void requestBattery(){
        if(batteryFree()){message("Battery optimization is already off for this app. Good.");return;}
        try{startActivity(new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,Uri.parse("package:"+getPackageName())));}
        catch(Exception e){open(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS));}
    }
    private void togglePause(){
        if(!SecureStore.configured(this)){message("Connect your server first.");return;}
        boolean enable=!SecureStore.enabled(this);
        SharedPreferences.Editor edit=SecureStore.prefs(this).edit().putBoolean("enabled",enable);
        if(enable)edit.putLong("capture_since",System.currentTimeMillis());
        edit.commit();
        if(enable){SyncEngine.schedule(this);SyncEngine.kick(this,null);KeepAliveService.start(this);NotificationListenerService.requestRebind(new ComponentName(this,PaymentListener.class));}
        else {SyncEngine.cancel(this);KeepAliveService.stop(this);SecureStore.status(this,"Paused. New payments are not captured while paused.");}
        refresh();
    }
    private void privacy(){
        message("This helper reads only recognized incoming-payment notifications from the Easypaisa package and certificate you trusted. It never logs in to your wallet or asks for your PIN, OTP, SMS, contacts or accessibility access.\n\nDevice token and queued payment text are encrypted with Android Keystore. After upload the text is removed; transaction IDs stay for duplicate detection. Backups are disabled.\n\nData goes only to your configured HTTPS server. No analytics. A notification is not bank-signed proof: review wallet history regularly.");
    }
    private void reset(){
        new AlertDialog.Builder(this).setTitle("Erase app data?")
            .setMessage("Deletes saved credentials and ALL queued payments, including unsent ones. Reconcile the wallet first.")
            .setNegativeButton("Cancel",null).setPositiveButton("Erase",(d,w)->{
                if(SyncEngine.isBusy()){message("Wait for the active sync to finish, then reset.");return;}
                SecureStore.prefs(this).edit().clear().commit();SyncEngine.cancel(this);KeepAliveService.stop(this);QueueDb.get(this).clear();
                url.setText("");device.setText("");token.setText("");token.setHint("Paste device token");refresh();
            }).show();
    }
    private void open(Intent i){try{startActivity(i);}catch(Exception e){message("Open this setting manually in Android Settings → Apps.");}}
    private void message(String s){new AlertDialog.Builder(this).setMessage(s).setPositiveButton("OK",null).show();}
    private String time(long v){return v==0?"not yet":DateFormat.getDateTimeInstance(DateFormat.SHORT,DateFormat.SHORT).format(new Date(v));}

    private void refresh(){
        if(status==null)return;
        SharedPreferences p=SecureStore.prefs(this);
        QueueDb q=QueueDb.get(this);
        long[] today=q.totalSince(startOfToday());
        todayAmt.setText("Rs "+money(today[1]));
        todayCount.setText(today[0]+" payment"+(today[0]==1?"":"s"));
        status.setText(!SecureStore.configured(this)?"Set up your connection":!SecureStore.enabled(this)?"Paused":p.getString("status","Ready to connect"));
        int pending=q.count("pending"),failed=q.count("failed");
        pendingInfo.setText(pending==0&&failed==0?"All payments synced":pending+" waiting to sync · "+failed+" need review");
        last.setText("Connection: "+time(p.getLong("last_heartbeat",0)));
        GradientDrawable pdot=new GradientDrawable();pdot.setShape(GradientDrawable.OVAL);pdot.setColor(SecureStore.enabled(this)?Color.rgb(140,255,190):Color.rgb(255,170,120));pulse.setBackground(pdot);

        checks.removeAllViews();
        checkRow("Server connected",SecureStore.configured(this),"Fill in server URL, Device ID and token below.",null);
        checkRow("Easypaisa trusted",TrustedApp.matches(this),"Trust your installed Easypaisa.",()->trustApp());
        checkRow("Notification Access on",notifAccess(),"Turn on Notification Access for this app.",()->notificationDisclosure());
        checkRow("Capture running",SecureStore.enabled(this),"Tap Save & connect, or Resume.",null);
        checkRow("Battery unrestricted",batteryFree(),"Allow background so payments are never missed.",()->requestBattery());
        pause.setText(SecureStore.enabled(this)?"Pause":"Resume");
        renderHistory();
    }
    private void renderHistory(){
        if(history==null)return;
        history.removeAllViews();
        List<QueueDb.Row> rows=QueueDb.get(this).history(search.getText().toString(),40);
        if(rows.isEmpty()){history.addView(text("No payments captured yet.",13,MUTED,false));return;}
        for(QueueDb.Row r:rows){
            LinearLayout item=new LinearLayout(this);item.setGravity(Gravity.CENTER_VERTICAL);item.setPadding(0,dp(10),0,dp(10));
            LinearLayout col=new LinearLayout(this);col.setOrientation(LinearLayout.VERTICAL);
            col.addView(text("Rs "+money(r.amount)+"   ·   "+(r.sender.isEmpty()?"-":r.sender),15,INK,true));
            col.addView(text("Trx "+r.tid+"  ·  "+time(r.observed),12,MUTED,false));
            if("failed".equals(r.state)&&!r.error.isEmpty())col.addView(text(r.error,12,RED,false));
            item.addView(col,new LinearLayout.LayoutParams(0,-2,1));
            int c=r.state.equals("sent")?G2:r.state.equals("failed")?RED:AMBER;
            String s=r.state.equals("sent")?"synced":r.state.equals("failed")?"review":"pending";
            TextView badge=text(s,12,c,true);GradientDrawable bg=new GradientDrawable();bg.setColor(Color.argb(28,Color.red(c),Color.green(c),Color.blue(c)));bg.setCornerRadius(dp(9));badge.setBackground(bg);badge.setPadding(dp(10),dp(4),dp(10),dp(4));
            item.addView(badge);
            history.addView(item);
            View sep=new View(this);sep.setBackgroundColor(LINE);history.addView(sep,new LinearLayout.LayoutParams(-1,1));
        }
    }
}
