#
# Asciidoc is configured to use docbook as the default backend in Ubuntu
# So forcing FOP is a little bit of a hack.
#
# In the directory images, you may need to run a command like
#
#  ln -s /usr/share/doc/asciidoc/doc/images/icons/ icons
#
# before building the documentation.
#
ALL: showdefault fop

showdefault:
	@echo "=================================================="
	@echo "Defaulting to FOP. You may choose fop/docbook/html"
	@echo "=================================================="

fop:
	a2x --icons -d book -f pdf --fop admin_guide.txt
	a2x --icons -d book -f pdf --fop user_guide.txt
	a2x --icons -d book -f pdf --fop dev_guide.txt

docbook:
	a2x  --icons -d book -f pdf admin_guide.txt
	a2x  --icons -d book -f pdf user_guide.txt
	a2x  --icons -d book -f pdf dev_guide.txt

html: admin_guide.html user_guide.html dev_guide.html

admin_guide.html : admin_guide.txt
	a2x --icons -d book -f xhtml -a toc admin_guide.txt

user_guide.html : user_guide.txt
	a2x --icons -d book -f xhtml -a toc user_guide.txt

dev_guide.html : dev_guide.txt
	#a2x --icons -d book -f xhtml -a toc -v dev_guide.txt #-- not used since source highlighting is not working with this.
	asciidoc -a toc dev_guide.txt

