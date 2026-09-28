public class Book extends Item {
    private int pages;

    public Book(int id, String title, String author, String genre,
                double rating, int pages) {
        super(id, title, author, genre, rating);
        this.pages = pages;
    }

    public int getPages() {
        return pages;
    }

    public String getType() {
        return "Book";
    }
}