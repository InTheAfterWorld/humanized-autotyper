package library_management_system;

public abstract class Item {

    private String title;
    private String author;
    private String genre;
    private double rating;
    private int id;
    private boolean availability;
    private String types;
    private boolean reserved;

    public Item (String _title_, String a, String g, double r, int _id_, boolean _availability_, String _types_){
        title = _title_;
        author = a;
        genre = g;
        rating = r;
        id = _id_;
        availability = _availability_;
        types = _types_;
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
}
