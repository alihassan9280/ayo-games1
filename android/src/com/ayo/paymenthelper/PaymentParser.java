package com.ayo.paymenthelper;

import java.math.BigDecimal;
import java.util.regex.*;
/** No Android dependency: tested on the build host. */
public final class PaymentParser {
    private static final Pattern FORMAT=Pattern.compile("^Trx ID (\\d{6,30})\\. You have Received Rs ((?:\\d+|\\d{1,3}(?:,\\d{3})+)\\.\\d{2}) from (.+?) with Easypaisa Account (92[\\d*]+)\\.?$");
    public static final class Payment {
        public final String tid,text,sender,account;
        public final long paisa;
        Payment(String id,String t,long a,String s,String acc){tid=id;text=t;paisa=a;sender=s;account=acc;}
    }
    public static Payment parse(String input) {
        if(input==null||input.length()>2000)return null;
        String text=input.trim().replaceAll("\\s+"," ");
        Matcher m=FORMAT.matcher(text);
        if(!m.matches()||m.group(4).length()!=12)return null;
        try {
            long amount=new BigDecimal(m.group(2).replace(",","")).movePointRight(2).longValueExact();
            if(amount<1||amount>100000000)return null;
            return new Payment(m.group(1),text,amount,m.group(3),m.group(4));
        }catch(Exception e){return null;}
    }
}
