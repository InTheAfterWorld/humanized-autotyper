public abstract class Item {

    private int id;
    private String title;
    private String author;
    private String genre;
    private double rating;
    private boolean available;

    public Item(int id, String title, String author, String genre, double rating) {
        this.id = id;
        this.title = title;
        this.author = author;
        this.genre = genre;
        this.rating = rating;
        this.available = true;
    }

    public int getId() {
        return id;
    }

    public String getTitle() {
        return title;
    }

    public String getAuthor() {
        return author;
    }

    public String getGenre() {
        return genre;
    }

    public double getRating() {
        return rating;
    }

    public boolean isAvailable() {
        return available;
    }

    public void setAvailable(boolean available) {
        this.available = available;
    }

    public abstract String getType();

    public String toString() {
        return id + " | " + getType() + " | " + title + " | "
                + author + " | " + genre + " | " + rating + " | "
                + (available ? "Available" : "Unavailable");
    }
}
