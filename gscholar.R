# gscholar_test.R

library(RSelenium)

# Run server rselenium -P---
remDr <- RSelenium::remoteDriver(remoteServerAddr = "localhost",
                                 port = 4444L,
                                 browserName = "firefox")
remDr$open()

# Navigate to Google Scholar----
remDr$navigate("https://scholar.google.com/")

# Send keyword to search box | set year, get url ----
# search_box <-  remDr$findElement(using = "xpath", value = '//input[@name = "q"]')
# Sys.sleep(2)
# search_box$sendKeysToElement(list('ChatGPT Educational Impact and Psychological Implications', key='enter'))
Sys.sleep(2)
# search_yr <- remDr$findElement(using = "css", value = ".gs_res_ab_dd_sec > a:nth-child(3)") # div.gs_res_ab_dd_sec > a:nth-child(2)
# url <- search_yr$getElementAttribute("href") # https://scholar.google.com/scholar? start=10 &q=fine+tune+llm&hl=en&as_sdt=0,5&as_ylo=2024
url_base <- "https://scholar.google.com.my/scholar?start="
url_tail <- "&q=ChatGPT+Educational+Impact+and+Psychological+Implications&hl=enen&as_sdt=0,5&as_vis=1" 
# https://scholar.google.com.my/scholar?start=10&q=ChatGPT+Educational+Impact+and+Psychological+Implications&hl=en&as_sdt=0,5&as_vis=1

# Function to get title, abstract and pdf file ----
get_titles <- function(url) {
    # Navigate to Google Scholar
    Sys.sleep(2)
    remDr$navigate(url)

    # Extract elems
    elem <- remDr$findElements(using = "css", value = 'h3.gs_rt')
    titles <- unlist(lapply(elem, function(x) {
        x$getElementText()
    }))

    return(titles)
}

get_pdf <- function(url) {
    # Navigate to Google Scholar
    Sys.sleep(5)
    remDr$navigate(url)
    
    # Extract elems
    elem <- remDr$findElements(using = "css selector", value = 'div.gs_ggsd a')
    pdf <- unlist(lapply(elem, function(x) {
        x$getElementAttribute("href")
    }))
    
    return(pdf)
}

get_abs <- function(url) {
    # Navigate to Google Scholar
    Sys.sleep(5)
    remDr$navigate(url)
    
    # Extract abstract
    elem <- remDr$findElements(using = "css selector", value = 'div.gs_rs')
    abs <- lapply(elem, function(x) {
        x$getElementText()
    })

    return(abs)
}

# get titles, pdf-link & abstract ----
# url <- paste0(url_base,x*10,url_tail)

titles <- unlist(lapply(c(0:13), function(x) get_titles(paste0(url_base,x*10,url_tail))))
pdf <- unlist(lapply(c(0:13), function(x) get_pdf(paste0(url_base,x*10,url_tail))))
abstract <- unlist(lapply(c(0:13), function(x) get_abs(paste0(url_base,x*10,url_tail))))

# save data ----
save.image("harvest.RData")

# save pdf link to pdf_link.txt ----
writeLines(pdf,"pdf_link.csv")
writeLines(abstract,"abstract.txt")
