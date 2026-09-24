import java.io.File;
import java.io.FileNotFoundException;
import java.util.Scanner;
import java.io.FileWriter;
import java.io.IOException;

public class PhoneNumberConverter {
	
	// A method that converts a letter to its corresponding number on a dial pad
	public static char letterToDigit(char c) {
	    c = Character.toUpperCase(c);

	    switch (c) {
	        case 'A': case 'B': case 'C':
	            return '2';
	        case 'D': case 'E': case 'F':
	            return '3';
	        case 'G': case 'H': case 'I':
	            return '4';
	        case 'J': case 'K': case 'L':
	            return '5';
	        case 'M': case 'N': case 'O':
	            return '6';
	        case 'P': case 'Q': case 'R': case 'S':
	            return '7';
	        case 'T': case 'U': case 'V':
	            return '8';
	        case 'W': case 'X': case 'Y': case 'Z':
	            return '9';
	        default:
	            return c;   // keep digits or symbols unchanged
	    }
	}
    
    // Method that determines whether a string is full of digits or not
	public static boolean isNumeric(String str) {
	    if (str == null || str.isEmpty()) return false;
	    for (char c : str.toCharArray()) {
	        if (!Character.isDigit(c)) return false;
	    } // End for
	    return true;
	}
	
	// Method that connects names and phone numbers
	public static String getName(String[] arr){
		return arr[0] + " " + arr[1];
	}

	public static String getRawDigits(String[] arr){
		String res = ""; // Initialize the variable that stores the raw digits
        // Go through the rest of the array to collect all the digits and letters from left to right
        for (int i = 2; i < arr.length; i++) {
            if (isNumeric(arr[i]) == false){ // If the phone number segment contains letters
                for (int j = 0; j < arr[i].length(); j++){
                    res = res + letterToDigit(arr[i].charAt(j));
                }
            } else {
                res = res + arr[i]; // Otherwise just add the numbers
            }
        } // End for
        return res;
	}

	public static String validateAndClean(String res) {
        // Check the assignment rules for 10 or 11 digits
        // Return null if it's less than 10 or more than 11
        if (res.length() < 10 || res.length() > 11) {
            return null;
        }

        // The first digit of an 11-digit number is always 1
        if (res.length() == 11) {
            if (res.charAt(0) == '1') {
                res = res.substring(1); // Remove the '1' to format the remaining 10 digits
            } else {
                return null;
            }
        }
        return res;
    }

	public static String applyFormatPattern(String res) {
        // Add dash and brackets at appropriate places (Format: (XXX) XXX-XXXX)
        if (res.length() == 10) {
            res = "(" + res.substring(0, 3) + ") " + res.substring(3, 6) + "-" + res.substring(6);
        }
        return res;
    }

	// Method that converts a line of input into a line of formatted names and numbers
	// String variable input indicates the input String
	public static String format(String input){
		if (input == null || input.isEmpty()){
            return "";
        }
        
        String[] arr = input.split("[ \\-()\\+]+"); // Split the String by spaces, brackets, and dashes

        // Ensure there is at least a first name, last name, and some phone data
        if (arr.length < 3){
            return input + " invalid number";
        }

        // The instructions say the first two items are always first name and last name
        String name = getName(arr);

        // Collect raw digits
        String res = getRawDigits(arr);

        // Validate and clean the digits
        res = validateAndClean(res);
        if (res == null) {
            return name + " invalid number";
        }

        // Format the numbers
        res = applyFormatPattern(res);

        // Add the name at the beginning of "res"
        res = name + " " + res;
        return res;
	}
	
	// Main method
	public static void main(String[] args) {
		
		// Import the file
		File phoneBook = new File("contacts.txt");
		
		// Create a new file to store the output
		File outputFile = new File("updatedContacts.txt");
		try {
		    outputFile.createNewFile();
		    
		} catch (Exception e) {
		    System.out.println("Could not create file");
		}
		
		// Read the file
		try (Scanner scanner = new Scanner(phoneBook);
	             FileWriter writer = new FileWriter(outputFile)) {
	             
	            while (scanner.hasNextLine()) { 
	                String line = scanner.nextLine();
	                String data = format(line);
	                
	                // Write the data and append a line break
	                if (!data.isEmpty()) {
	                    writer.write(data + System.lineSeparator());
	                }
	            } // End while
	            
	            System.out.println("Contacts successfully updated!");

	        } catch (FileNotFoundException e) {
	            System.out.println("Error: Could not find the input file.");
	            e.printStackTrace();
	        } catch (IOException e) {
	            System.out.println("Error: Could not read/write to the file.");
	            e.printStackTrace();
	        }
	}
}