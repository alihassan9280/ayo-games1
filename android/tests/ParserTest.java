import com.ayo.paymenthelper.PaymentParser;
public class ParserTest {
    private static void check(boolean condition){if(!condition)throw new AssertionError();}
    public static void main(String[] args){
        String sample="Trx ID 12345678901. You have Received Rs 8.00 from TEST SENDER with Easypaisa Account 923004****13.";
        PaymentParser.Payment p=PaymentParser.parse(sample);
        check(p!=null&&p.paisa==800&&p.tid.equals("12345678901"));
        check(PaymentParser.parse(sample.replace("8.00","1,234.56")).paisa==123456);
        check(PaymentParser.parse(sample.replace("Received","Sent"))==null);
        check(PaymentParser.parse(sample.replace("8.00","-8.00"))==null);
        check(PaymentParser.parse(sample.replace("8.00","8,0.00"))==null);
        check(PaymentParser.parse(sample.replace("8.00","0.00"))==null);
        check(PaymentParser.parse(sample.replace("8.00","1000001.00"))==null);
        check(PaymentParser.parse("OTP is 123456")==null);
        check(PaymentParser.parse(null)==null);
        check(PaymentParser.parse(sample.replace(" from ","\nfrom ")).paisa==800);
        check(PaymentParser.parse(sample.replace("923004****13","92300413"))==null);
        System.out.println("11 payment parser checks passed.");
    }
}
