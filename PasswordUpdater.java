import java.io.*;
import java.util.*;

public class PasswordUpdater {
    public static void main(String[] args) {

        ArrayList<String> list = new ArrayList<>(); // Create the String ArrayList to store original passwords

        // Read the original passwords from the file and store them in the ArrayList
        try {
            Scanner sc = new Scanner(new File("passwords.txt"));

            while (sc.hasNextLine()) {
                String s = sc.nextLine().trim();

                if (!s.isEmpty()) {
                    list.add(s);
                }
            }

            sc.close();

        } catch (FileNotFoundException e) {
            System.out.println("File not found.");
            return;
        }

        // Process each password in the list
        // Traverse the list of passwords and update them one by one
        for (int i = 0; i < list.size(); i++) {

            String s = list.get(i);
            StringBuilder p = new StringBuilder(s); // Use StringBuilder for easier manipulation

            String sp = "!@#$%^&*"; // String of special characters

            // 1. Insert 2 random special characters
            for (int j = 0; j < 2; j++) {
                char c = sp.charAt((int)(Math.random() * sp.length())); // Find a random special character from the string
                int x = (int)(Math.random() * (p.length() + 1)); // Find a random index in the password
                p.insert(x, c); //Insert the special character
            }

            // Insert 2 random digits
            for (int j = 0; j < 2; j++) {
                char c = (char)('0' + (int)(Math.random() * 10));
                int x = (int)(Math.random() * (p.length() + 1));
                p.insert(x, c);
            }
            
            int letter = 0; // Counter for the number of letters

            // Check if the password has at least 2 letters
            for (int j = 0; j < p.length(); j++) {
                char c = p.charAt(j);

                if (Character.isLetter(c)) {
                    letter++; // Increment the counter
                }
            }

            while (letter < 2) {
                int x = (int)(Math.random() * p.length()); // Find a random index in the password
                char c = p.charAt(x); // Get the character at that index

                if (Character.isLowerCase(c)) { // Check if the character is a lowercase letter
                    p.setCharAt(x, Character.toUpperCase(c)); // Capitalize the letter
                    letter++; // Increment the counter
                }
            }
            
            list.set(i, p.toString()); // Modify the current password in the list
        }

        list.sort(Comparator.comparingInt(String::length)); // Sort the list by length in ascending order

        // Output
        for (String s : list) {
            System.out.println(s);
        }

        try {
            PrintWriter out = new PrintWriter("newpasswords.txt");

            for (String s : list) {
                out.println(s);
            }

            out.close();

        } catch (FileNotFoundException e) {
            System.out.println("Error writing file.");
        }
    }
}

