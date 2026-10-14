package com.ayo.paymenthelper;

import android.app.job.*;
import android.content.*;
import java.net.*;
import javax.net.ssl.HttpsURLConnection;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.concurrent.*;
import org.json.*;

public final class SyncEngine {
    // One executor serializes all upload passes in this process.
    private static final ExecutorService EXEC=Executors.newSingleThreadExecutor();
    private static final java.util.concurrent.atomic.AtomicInteger ACTIVE=new java.util.concurrent.atomic.AtomicInteger();
    public static boolean isBusy(){return ACTIVE.get()>0;}
    public static void kick(Context context,Runnable after){
        Context c=context.getApplicationContext();
        ACTIVE.incrementAndGet();
        EXEC.execute(()->{try{sync(c);}finally{ACTIVE.decrementAndGet();if(after!=null)after.run();}});
    }
    public static String normalizeUrl(String value)throws Exception {
        URI uri=new URI(value.trim());
        if(!"https".equalsIgnoreCase(uri.getScheme())||uri.getHost()==null||uri.getUserInfo()!=null||
            uri.getQuery()!=null||uri.getFragment()!=null||!(uri.getPath().isEmpty()||uri.getPath().equals("/")))
            throw new IllegalArgumentException("Use an HTTPS server origin, e.g. https://payments.example.com");
        return new URI("https",null,uri.getHost(),uri.getPort(),null,null,null).toString();
    }
    private static int post(Context c,String endpoint,JSONObject json)throws Exception{
        String url=normalizeUrl(SecureStore.prefs(c).getString("url",""));
        HttpsURLConnection con=(HttpsURLConnection)new URL(url+endpoint).openConnection();
        try{
            con.setInstanceFollowRedirects(false);
            con.setRequestMethod("POST");con.setConnectTimeout(10000);con.setReadTimeout(15000);
            con.setRequestProperty("Content-Type","application/json");
            con.setRequestProperty("Authorization","Bearer "+SecureStore.token(c));
            con.setRequestProperty("X-Device-ID",SecureStore.prefs(c).getString("device",""));
            con.setDoOutput(true);
            byte[] data=json.toString().getBytes(StandardCharsets.UTF_8);
            con.setFixedLengthStreamingMode(data.length);
            try(OutputStream os=con.getOutputStream()){os.write(data);}
            int code=con.getResponseCode();
            // Require the expected API JSON, not just a captive portal's 200 response.
            if(code>=200&&code<300){
                ByteArrayOutputStream buf=new ByteArrayOutputStream();
                try(InputStream in=con.getInputStream()){
                    byte[] chunk=new byte[1024];int n;
                    while((n=in.read(chunk))!=-1){if(buf.size()+n>8192)throw new IOException("Invalid response");buf.write(chunk,0,n);}
                }
                JSONObject result=new JSONObject(buf.toString("UTF-8"));
                String field=endpoint.endsWith("/payments")?"accepted":"ok";
                if(!result.optBoolean(field,false))throw new IOException("Unexpected API response");
            }
            return code;
        }finally{con.disconnect();}
    }
    public static void schedule(Context c){
        if(!SecureStore.enabled(c))return;
        JobScheduler js=(JobScheduler)c.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        ComponentName service=new ComponentName(c,SyncJob.class);
        js.schedule(new JobInfo.Builder(101,service).setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
            .setMinimumLatency(1000).setBackoffCriteria(30000,JobInfo.BACKOFF_POLICY_EXPONENTIAL).build());
        if(js.getPendingJob(102)==null)
            js.schedule(new JobInfo.Builder(102,service).setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setPersisted(true).setPeriodic(15*60*1000L).build());
    }
    public static void cancel(Context c){
        JobScheduler js=(JobScheduler)c.getSystemService(Context.JOB_SCHEDULER_SERVICE);js.cancel(101);js.cancel(102);
    }
    private static String error(int code){
        if(code==401||code==403)return "Device not authorized. Check token or register again.";
        if(code==409)return "Conflicting transaction. Review backend records.";
        if(code==400||code==422)return "Backend rejected format/time. Check phone clock and backend.";
        if(code>=300&&code<400)return "Redirect blocked. Enter the final HTTPS API URL.";
        if(code==429)return "Rate limited; queued for retry.";
        return "Server HTTP "+code;
    }
    private static void sync(Context c){
        if(!SecureStore.enabled(c))return;
        QueueDb db=QueueDb.get(c);
        try{
            for(QueueDb.Item item:db.ready()){
                if(!SecureStore.enabled(c))break;
                if(System.currentTimeMillis()-item.observed>7L*86400000){
                    db.failed(item,"Older than 7 days; reconcile manually.",true);continue;
                }
                try{
                    JSONObject payload=new JSONObject().put("notification_text",SecureStore.decrypt(item.payload))
                        .put("observed_at",Instant.ofEpochMilli(item.observed).toString());
                    int code=post(c,"/v1/device/payments",payload);
                    if(code>=200&&code<300){
                        db.sent(item.tid);SecureStore.prefs(c).edit().putLong("last_sync",System.currentTimeMillis()).apply();
                        SecureStore.status(c,"Payment synced to your backend.");
                    }else{
                        boolean permanent=code>=400&&code<500&&code!=408&&code!=429;
                        db.failed(item,error(code),permanent);SecureStore.status(c,error(code));
                        if(code==401||code==403||code==429||code>=500)break;
                    }
                }catch(Exception e){
                    db.failed(item,"Connection/encryption error; retry pending.",false);
                    SecureStore.status(c,"Cannot sync. Check internet, HTTPS address and device token.");break;
                }
            }
            // Heartbeat is a connection test, never a fake payment.
            if(SecureStore.enabled(c)){
                int code=post(c,"/v1/device/heartbeat",new JSONObject());
                if(code>=200&&code<300){
                    SecureStore.prefs(c).edit().putLong("last_heartbeat",System.currentTimeMillis()).apply();
                    if(db.count("pending")==0&&db.count("failed")==0)SecureStore.status(c,"Connected. Waiting for a payment notification.");
                }else SecureStore.status(c,error(code));
            }
        }catch(Exception e){SecureStore.status(c,"Cannot reach backend. Check HTTPS URL, internet and credentials.");}
    }
}
