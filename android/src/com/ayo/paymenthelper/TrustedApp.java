package com.ayo.paymenthelper;
import android.content.*;
import android.content.pm.*;
import android.os.Build;
import java.security.MessageDigest;
import java.util.*;

public final class TrustedApp {
    public static final String PACKAGE="pk.com.telenor.phoenix";
    @SuppressWarnings("deprecation")
    public static List<String> signatures(Context c)throws Exception {
        PackageManager pm=c.getPackageManager();
        Signature[] signatures;
        if(Build.VERSION.SDK_INT>=28) {
            PackageInfo p=pm.getPackageInfo(PACKAGE,PackageManager.GET_SIGNING_CERTIFICATES);
            signatures=p.signingInfo.hasMultipleSigners()?p.signingInfo.getApkContentsSigners():p.signingInfo.getSigningCertificateHistory();
        }else signatures=pm.getPackageInfo(PACKAGE,PackageManager.GET_SIGNATURES).signatures;
        List<String> out=new ArrayList<>();
        for(Signature sig:signatures){
            byte[] h=MessageDigest.getInstance("SHA-256").digest(sig.toByteArray());
            StringBuilder b=new StringBuilder();for(byte v:h)b.append(String.format(Locale.US,"%02x",v&255));
            out.add(b.toString());
        }
        return out;
    }
    public static boolean matches(Context c){
        String pin=SecureStore.prefs(c).getString("signer","");
        if(pin.isEmpty())return false;
        try{return signatures(c).contains(pin);}catch(Exception e){return false;}
    }
}
