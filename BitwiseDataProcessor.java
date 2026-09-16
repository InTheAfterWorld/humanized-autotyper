import java.util.Arrays;
import java.util.Random;

public class BitwiseDataProcessor{

    public static void storeElement(int num, int index, byte[] arr){

        int firstIndex = (index * 9) / 8; // Index of the first part of the 9-bit number in the new byte array
        int bitsShift = index * 9 % 8; // The number of digits that has to be move so that the first part of the number in binary that will be stored in the byte array

        // Shift the digits of the two parts
        byte firstNum = (byte) ((num & 0x1FF) << bitsShift);
        byte secondNum = (byte) ((num & 0x1FF) >>> (8 - bitsShift));

        // Add them to the array
        arr[firstIndex] |= firstNum;
        arr[firstIndex + 1] |= secondNum;
    }

    public static int readElement(int index, byte[] arr){

        // Define the variables to reverse the process in storeElement
        int bitPosition = index * 9;
        int firstIndex = bitPosition / 8;
        int bitsShift = bitPosition % 8;

        int firstByte = arr[firstIndex] >>> bitsShift; // The first part of the number
        int secondByte = arr[firstIndex + 1] << (8 - bitsShift); // The second part of the number

        int num = (firstByte | secondByte) & 0x1FF; // Format the output

        if (num >= 256) {
            num -= 512;
        }

        return num;
    }

    public static void printElements(byte[] arr){

        // Traverse the array
        for (int i = 0; i < arr.length * 8 / 9; i++){

            // Define the variables to reverse the process in storeElement
            int bitPosition = i * 9;
            int firstIndex = bitPosition / 8;
            int bitsShift = bitPosition % 8;

            int firstByte = arr[firstIndex] >>> bitsShift; // The first part of the number
            int secondByte = arr[firstIndex + 1] << (8 - bitsShift); // The second part of the number

            int num = (firstByte | secondByte) & 0x1FF; // Format the output

            if (num >= 256) {
                num -= 512;
            }

            System.out.println(num); // Output
        }
    }

    public static void main(String[] args) {
        Random random = new Random();

        int numberOfElements = 10;

        // Creates the original array with random values between -256 and 255
        int[] originalArray = new int[numberOfElements];
        for (int i = 0; i < numberOfElements; i++) {
            originalArray[i] = random.nextInt(512) - 256; 
        }
    
        byte[] byteArray = new byte[(int)(Math.ceil(9 * (double) numberOfElements / 8))]; // Initialize the resulting byte array.

        for(int i = 0; i < originalArray.length; i++){

            storeElement(originalArray[i], i, byteArray);
        }

        System.out.println(Arrays.toString(originalArray));
        System.out.println(Arrays.toString(byteArray));

        Arrays.sort(originalArray);

        byte[] sortedByteArray = new byte[byteArray.length];

        for(int i = 0; i < originalArray.length; i++){
            storeElement(originalArray[i], i, sortedByteArray);
        }

        System.out.println(Arrays.toString(originalArray));
        printElements(sortedByteArray);

    }
}