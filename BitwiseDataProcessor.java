import java.util.Arrays;
import java.util.Random;

public class BitwiseDataProcessor{

    public static void storeElement(int num, int index, byte[] arr){

        int firstIndex = (index * 9) / 8; // Index of the first part of the 9-bit number in the new byte array
        int bitsShift = index * 9 % 8; // The number of digits that has to be move so that the first part of the number in binary that will be stored in the byte array

        int num9 = num & 0x1FF; // Extract only the lower bits

        byte firstNum = (byte) (num9 << bitsShift);
        byte secondNum = (byte) (num9 >>> (8 - bitsShift));

        arr[firstIndex] |= firstNum;
        arr[firstIndex + 1] |= secondNum;
    }

    

    public static void main(String[] args) {
        Random random = new Random();

        int numberOfElements = 10;

        // Creates the original array with random values between -256 and 255
        int[] originalArray = new int[numberOfElements];
        for (int i = 0; i < numberOfElements; i++) {
            originalArray[i] = random.nextInt(512) - 256; 
        }

        byte[] resArray = new byte[(int)(Math.ceil(9 * (double) numberOfElements / 8))]; // Initialize the resulting byte array.

    }
}

/*
public class BitwiseDataProcessor {

    public static void main(String[] args) {
        int numberOfElements = 10;

        int[] originalArray = new int[numberOfElements];
        for (int i = 0; i < numberOfElements; i++) {
            originalArray[i] = random.nextInt(512) - 256; 
        }

        int totalBytes = (int) Math.ceil((numberOfElements * 9) / 8.0);
        byte[] byteArray = new byte[totalBytes];

        for (int i = 0; i < numberOfElements; i++) {
            storeElement(originalArray[i], i, byteArray);
        }

        System.out.println("--- BEFORE SORTING ---");
        System.out.println("Original Array: " + Arrays.toString(originalArray));
        System.out.print("Byte Array (Decoded): ");
        printElements(byteArray, numberOfElements);

        Arrays.sort(originalArray);

        int[] tempUnpacked = new int[numberOfElements];
        for (int i = 0; i < numberOfElements; i++) {
            tempUnpacked[i] = readElement(byteArray, i);
        }
        Arrays.sort(tempUnpacked);
        for (int i = 0; i < numberOfElements; i++) {
            storeElement(tempUnpacked[i], i, byteArray);
        }

        System.out.println("\n--- AFTER SORTING ---");
        System.out.println("Original Array: " + Arrays.toString(originalArray));
        System.out.print("Byte Array (Decoded): ");
        printElements(byteArray, numberOfElements);
    }

    public static void storeElement(int value, int index, byte[] array) {
        // Mask the value to 9 bits to eliminate any sign extension garbage
        int maskedValue = value & 0x1FF;

        // Calculate the starting bit position in the byte array
        int bitPosition = index * 9;
        int byteIndex = bitPosition / 8;
        int bitOffset = bitPosition % 8;

        // A 9-bit value can span across up to 3 bytes (if bitOffset is 7, it spans 7, 8, 1)
        // Clear the space where the 9 bits will go and overlay the new bits
        long bitMask = 0x1FFL << bitOffset;
        
        // Read existing bytes into a temporary 64-bit long to safely manipulate across boundaries
        long currentBytes = 0;
        for (int i = 0; i < 3; i++) {
            if (byteIndex + i < array.length) {
                currentBytes |= ((long) (array[byteIndex + i] & 0xFF)) << (i * 8);
            }
        }

        // Clear the old 9 bits, inject the new masked 9 bits
        currentBytes &= ~bitMask;
        currentBytes |= ((long) maskedValue) << bitOffset;

        // Write the modified bits back into the byte array
        for (int i = 0; i < 3; i++) {
            if (byteIndex + i < array.length) {
                array[byteIndex + i] = (byte) ((currentBytes >> (i * 8)) & 0xFF);
            }
        }
    }

    public static int readElement(byte[] array, int index) {
        int bitPosition = index * 9;
        int byteIndex = bitPosition / 8;
        int bitOffset = bitPosition % 8;

        // Read up to 3 bytes to fully capture the 9 bits across boundaries
        long currentBytes = 0;
        for (int i = 0; i < 3; i++) {
            if (byteIndex + i < array.length) {
                currentBytes |= ((long) (array[byteIndex + i] & 0xFF)) << (i * 8);
            }
        }

        // Extract the 9 bits by shifting right and masking
        int value = (int) ((currentBytes >> bitOffset) & 0x1FF);

        // Sign extend the 9-bit value back into a 32-bit Java signed int
        // If the 9th bit (index 8) is 1, it's a negative number
        if ((value & 0x100) != 0) {
            value |= 0xFFFFFE00; // Pad the upper bits with 1s
        }

        return value;
    }

    public static void printElements(byte[] array, int totalElements) {
        int[] decoded = new int[totalElements];
        for (int i = 0; i < totalElements; i++) {
            decoded[i] = readElement(array, i);
        }
        System.out.println(Arrays.toString(decoded));
    }
}
*/