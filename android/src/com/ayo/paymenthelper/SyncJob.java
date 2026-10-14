package com.ayo.paymenthelper;
import android.app.job.*;
public final class SyncJob extends JobService {
    public boolean onStartJob(JobParameters params){
        KeepAliveService.start(this);
        SyncEngine.kick(this,()->jobFinished(params,SecureStore.enabled(this)&&QueueDb.get(this).count("pending")>0));
        return true;
    }
    public boolean onStopJob(JobParameters params){return SecureStore.enabled(this);}
}
